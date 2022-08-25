import pandas as pd
import numpy as np

n = 10
df = pd.DataFrame({"A": [ i for i in range(n) ]}, 
                   index = pd.date_range("2022-08-25", periods = n, freq = 'S'))
print(df)

'''
                     A
2022-08-25 00:00:00  0
2022-08-25 00:00:01  1
2022-08-25 00:00:02  2
2022-08-25 00:00:03  3
2022-08-25 00:00:04  4
2022-08-25 00:00:05  5
2022-08-25 00:00:06  6
2022-08-25 00:00:07  7
2022-08-25 00:00:08  8
2022-08-25 00:00:09  9
'''

sample_rate = 3
df = df.resample(f'{sample_rate}S', offset = '1S').mean()
print(df)

'''
                       A
2022-08-24 23:59:58  0.0
2022-08-25 00:00:01  2.0
2022-08-25 00:00:04  5.0
2022-08-25 00:00:07  8.0
'''