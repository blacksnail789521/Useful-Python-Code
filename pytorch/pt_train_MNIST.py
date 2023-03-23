import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import os
import netron
import matplotlib.pyplot as plt

# import lightning as L
import pytorch_lightning as L  # 2.0.0

# from lightning.pytorch.callbacks import ModelCheckpoint, EarlyStopping
from pytorch_lightning.callbacks import ModelCheckpoint, EarlyStopping

import torchmetrics
import numpy as np
from datetime import datetime
from ray.tune.integration.pytorch_lightning import TuneReportCheckpointCallback

from pt_load_MNIST import load_MNIST, show_data
from pt_load_MNIST_DataModule import MNIST_DataModule
from models.MLP import MLP
from models.CNN import CNN
from models.LightningModuleWrapper import LightningModuleWrapper


def plot_model_with_netron(model: nn.Module, name: str = "DNN") -> None:
    # Save the model
    model_path = os.path.join("saved_models", f"{name}.pt")
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    torch.save(model, model_path)  # Don't use .state_dict()

    # Plot the model
    netron.start(model_path, address=8081)


def train_model(
    train_dl: DataLoader,
    val_dl: DataLoader,
    model: L.LightningModule,
    epochs: int = 3,
    enable_checkpointing: bool = True,
    enable_logging: bool = True,
    additional_callbacks: list = [],
    use_gpu: bool = False,
    ray_tune: bool = False,
) -> L.Trainer:
    # Set callbacks
    callbacks = []
    # (We don't need to set the tensorboard logger because it is set by default)
    if enable_checkpointing:
        # We don't want to use the default one because it doesn't save all models
        # We need to save all models because we want to use the best model for the test set
        model_checkpoint = ModelCheckpoint(
            monitor="val_loss",
            mode="min",
            filename="{epoch:02d}-{val_loss:.4f}",
            save_top_k=-1,  # save all models
            save_weights_only=True,
        )
        callbacks.append(model_checkpoint)
    early_stopping_with_TerminateOnNaN = EarlyStopping(
        monitor="val_loss", mode="min", patience=3, verbose=True
    )
    callbacks.append(early_stopping_with_TerminateOnNaN)
    callbacks.extend(additional_callbacks)

    # Set trainer
    default_root_dir = os.path.join(
        "ray_results",
        f"{model.name}",
        f"tune_MNIST_000",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    # if ray_tune:
    #     os.makedirs(os.path.join(default_root_dir, "lightning_logs"), exist_ok=True)
    device_config = {}
    if not use_gpu:
        device_config["accelerator"] = "cpu"
    else:
        device_config["accelerator"] = "gpu"
        device_config["devices"] = "auto"
        # device_config["devices"] = 4
        # device_config["devices"] = [0, 1, 2, 3]
        device_config["strategy"] = "ddp"  # Since 2.0.0, we need to use ddp
        # device_config[
        #     "strategy"
        # ] = "ddp_find_unused_parameters_false"  # Allow to have unused parameters
    trainer = L.Trainer(
        default_root_dir=default_root_dir,
        max_epochs=epochs,
        log_every_n_steps=50,  # default: 50
        callbacks=callbacks,
        enable_checkpointing=enable_checkpointing,
        logger=enable_logging,
        # We don't need to save the model because we use ModelCheckpoint
        **device_config,
    )

    # Train the model
    trainer.fit(model, train_dl, val_dl)

    return trainer


def test_model(
    model: L.LightningModule,
    trainer: L.Trainer,
    test_dl: DataLoader,
) -> dict:
    """
    # Method 1: don't pass the model so that the best model is automatically loaded
    loss_list = trainer.test(dataloaders=test_dl)

    # Method 2: pass the model and specify the ckpt_path
    loss_list = trainer.test(model, test_dl, ckpt_path="best")

    # Method 3: load the best model manually, and then pass it to the trainer
    model.load_state_dict(
        torch.load(trainer.checkpoint_callback.best_model_path)["state_dict"]
    )
    loss_list = trainer.test(model, test_dl)
    """
    # Test the model
    loss_list = trainer.test(model, test_dl, ckpt_path="best")

    # The length of the loss_list corresponds to the number of dataloaders used.
    test_loss_dict = loss_list[0]

    return test_loss_dict


def plot_predictions(
    model: L.LightningModule,
    trainer: L.Trainer,
    test_dl: DataLoader,
) -> None:
    # Get all the predictions (y_pred_list[0].shape: (32, 10))
    y_pred_list = trainer.predict(model, dataloaders=test_dl)
    y_pred = y_pred_list[0]  # Extract the first batch  # type: ignore

    # Show the first 5 predictions
    x, y = next(iter(test_dl))
    for i in range(5):
        plt.imshow(x[i, 0, :, :], cmap="gray")
        plt.title(f"Label: {y[i]}, Prediction: {np.argmax(y_pred[i])}")
        plt.show()


def trainable(
    tunable_params: dict,
    fixed_params: dict,
    ray_tune: bool = True,
    use_lightning_data_module: bool = True,
    data_dir: str = "./",
) -> None:
    # Load data
    if not use_lightning_data_module:
        train_dl, test_dl = load_MNIST(batch_size=tunable_params["batch_size"])
        val_dl = test_dl
    else:
        dm = MNIST_DataModule(
            data_dir=data_dir, batch_size=tunable_params["batch_size"], split=0.8
        )
        dm.prepare_data()
        dm.setup()
        train_dl = dm.train_dataloader()
        val_dl = dm.val_dataloader()
        test_dl = dm.test_dataloader()
    if not ray_tune:
        show_data(train_dl)  # Show the data

    # Get the model
    if fixed_params["model_name"] == "MLP":
        model = MLP(tunable_params["num_layers"])
    elif fixed_params["model_name"] == "CNN":
        model = CNN(tunable_params["num_conv_layers"])
    else:
        raise ValueError(f"Unknown model: {fixed_params['model_name']}")

    model = LightningModuleWrapper(
        model=model,
        l2_weight=tunable_params["l2_weight"],
        optimizer=tunable_params["optimizer"],
        lr=tunable_params["lr"],
        loss=fixed_params["loss"],
        metrics=fixed_params["metrics"],
    )
    if not ray_tune:
        print(model)

        # Plot the model
        # plot_model_with_netron(model)

    # Determine additional_callbacks (for logging/plotting purposes only)
    additional_callbacks = []
    if not ray_tune:
        # PyTorch Lightning will handle it automatically
        pass
    else:
        additional_callbacks.append(
            TuneReportCheckpointCallback(
                # metrics={"val_loss": "val_loss", "val_accuracy": "val_accuracy"},
                metrics=["val_loss", "val_accuracy"],
                # filename="checkpoint", # (default)
            )
        )

    # Train
    print("---------------------------------------")
    print("Training ...")
    trainer = train_model(
        train_dl,
        val_dl,
        model,
        epochs=tunable_params["epochs"],
        additional_callbacks=additional_callbacks,
        enable_checkpointing=not ray_tune,
        enable_logging=not ray_tune,
        # TuneReportCheckpointCallback will handle checkpointing and logging
        use_gpu=fixed_params["use_gpu"],
        ray_tune=ray_tune,
    )

    if not ray_tune:
        # Test
        print("---------------------------------------")
        print("Testing ...")
        test_loss = test_model(model, trainer, test_dl)

        # Predict
        print("---------------------------------------")
        print("Predicting ...")
        plot_predictions(model, trainer, test_dl)


if __name__ == "__main__":
    fixed_params = {
        # "model_name": "MLP",
        "model_name": "CNN",
        "loss": "cross_entropy",
        "metrics": ["cross_entropy", "accuracy"],
        # We must initialize the torchmetrics inside the model
        "use_gpu": True,  # if True, please use script to run the code
    }
    tunable_params = {
        "batch_size": 256,
        "optimizer": "Adam",
        "lr": 0.001,
        "l2_weight": 0.01,
        "epochs": 3,
    }
    if fixed_params["model_name"] == "MLP":
        tunable_params["num_layers"] = 3
    elif fixed_params["model_name"] == "CNN":
        tunable_params["num_conv_layers"] = 3

    # Set all random seeds (Python, NumPy, PyTorch)
    L.seed_everything(seed=0)

    # Set the precision of the matrix multiplication
    torch.set_float32_matmul_precision("high")

    trainable(tunable_params, fixed_params, ray_tune=False)