import time

import pandas as pd
import numpy as np
from atrader import *
from datetime import datetime

stock_data_30 = pd.read_csv(r"C:\Users\李敏建\Downloads\6cdbab70-1b7d-42a8-b3e5-386bc18b61ad\A题\附录一：30支股票行情.csv")
stock_id = stock_data_30["code"].drop_duplicates().values.tolist()

print(len(stock_id))
total_money = 1000555


def init(context):
    # 账号设置：设置初始资金为 10000000 元
    set_backtest(initial_cash=total_money, future_cost_fee=1.0, stock_cost_fee=2.5, margin_rate=1.0, slide_price=0,
                 price_loc=1, deal_type=0, limit_type=0)
    # 注册数据：日频数据
    reg_kdata('day', 1)
    context.Len = 5  # 时间长度: 当交易日个数小于该事件长度时，跳过该交易日，假设每周五个交易日
    context.Num = 0  # 记录当前交易日个数
    # 确保周初调仓
    days = get_trading_days('SSE', '2011-01-01', '2020-11-01')
    is_monday = np.vectorize(lambda x: x.strftime("%w"))(days)
    is_monday = [is_monday == "1"]
    week_begin = days[is_monday]
    context.week_begin = pd.Series(week_begin).dt.strftime('%Y-%m-%d').tolist()


def on_data(context):
    context.Num = context.Num + 1
    if context.Num < context.Len:  # 如果交易日个数小于Len+1，则进入下一个交易日进行回测
        return
    if datetime.strftime(context.now, '%Y-%m-%d') not in context.week_begin:  # 调仓频率为月,月初开始调仓
        return
    KData = get_reg_kdata(reg_idx=context.reg_kdata[0], length=context.Len, fill_up=True, df=True)
    # K线数据序号对齐
    tempIdx = KData[KData['time'] == KData['time'][0]]['target_idx'].reset_index(drop=True)

    benefit_dic = {}
    for i in range(len(stock_id)):
        # 提取当前标的的前一周的K线面板数据
        close = np.array(KData[KData['target_idx'] == tempIdx[i]]['close'])
        # 计算当前标的在上周的收益率
        benefit = (close[-1] - close[0]) / close[0]
        benefit_dic[tempIdx[i]] = benefit
    print("on_data")

    target_dic = dict(sorted(benefit_dic.items(), key=lambda item: item[1], reverse=True))
    target_code = list(target_dic.keys())[:10]
    order_close_all(account_idx=0)
    print("target_code=", target_code)
    # 建仓操作
    for i in target_code:
        order_percent(account_idx=0, target_idx=i, percent=0.1, side=1, position_effect=1,
                      order_type=2,
                      price=0)


if __name__ == '__main__':
    begin_date = '2011-01-01'
    end_date = '2020-11-01'

    strategy_name = 'simple'

    run_backtest(strategy_name=strategy_name,
                 target_list=stock_id,
                 frequency='day', fre_num=1, begin_date=begin_date, end_date=end_date, fq=1)
