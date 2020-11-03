import time

import pandas as pd
import numpy as np
from atrader import *
from datetime import datetime

stock_data_30 = pd.read_csv(r"C:\Users\李敏建\Downloads\6cdbab70-1b7d-42a8-b3e5-386bc18b61ad\A题\附录一：30支股票行情.csv")
stock_id = stock_data_30["code"].drop_duplicates().values.tolist()

print(len(stock_id))
total_money = 1000000

num = 0


def init(context):
    # 账号设置：设置初始资金为 10000000 元
    set_backtest(initial_cash=total_money, future_cost_fee=1.0, stock_cost_fee=2.5, margin_rate=1.0, slide_price=0,
                 price_loc=1, deal_type=0, limit_type=0)
    # 注册数据：日频数据
    reg_kdata('day', 1)


def on_data(context):
    target_code = [1, 3, 4, 9, 11, 19, 17, 23, 21, 16, 15]
    order_close_all(account_idx=0)
    print("target_code=", target_code)
    # 建仓操作
    for i in target_code:
        order_value(account_idx=0, target_idx=i, value=total_money / 10, side=1, position_effect=1,
                    order_type=2,
                    price=0)
    position = context.account().position()  # 多头持仓数量
    if position is not None:
        position_codes = position["target_idx"]
        print("position_codes=", position_codes.tolist())


if __name__ == '__main__':
    begin_date = '2011-01-01'
    end_date = '2020-11-01'

    strategy_name = 'simple'

    run_backtest(strategy_name=strategy_name,
                 target_list=stock_id,
                 frequency='day', fre_num=1, begin_date=begin_date, end_date=end_date, fq=1)
