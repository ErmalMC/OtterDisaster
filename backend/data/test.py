import pandas as pd
df = pd.read_csv("output.csv")
print(df.columns.tolist())
print(df.tail(5))