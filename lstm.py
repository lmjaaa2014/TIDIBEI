"""
----------------------------------------------------------
策略思路：
1. 回测标的：沪深300成分股
2. 回测时间段：2016-01-01 至 2018-09-30
3. 特征选择：
	- 基础类：AdminExpenseTTM, FinanExpenseTTM, NetIntExpense, GrossProfit
    - 质量类：ROIC, CashToCurrentLiability
    - 收益风险类：DDNCR    
    - 情绪类：PVI
	- 成长类：TotalAssetGrowRate
	- 常用技术指标类：MA120
	- 动量类：AD
	- 价值类：PS
    - 每股指标类：EnterpriseFCFPS
    - 行业分析师：FY12P
    - 特色技术指标：STDDEV
4. 单因子回归测试模型思路：
    1. 先获得 21 天以上的K线数据和因子数据，预处理
    2. 使用上月初的多个因子和上月收益率进行线性回归
    3. 使用【LSTM模型】进行训练
    4. 回到当前时间点，使用本月初的因子作为预测样本特征，预测本月的各股票平均收益率的大小。
5. 选股逻辑：
    将符合预测结果的股票按均等分配可用资金进行下单交易。持有一个月后 ，再次进行调仓，训练预测。
6. 交易逻辑：
    每次调仓时，若当前有持仓，并且符合选股条件，则仓位不动；
                              若不符合选股条件，则对收益低的标的进行仓位平仓；
                若当前无仓，并且符合选股条件，则多开仓，对收益高的标的进行开仓；
                            若不符合选股条件，则不开仓，无需操作。
----------------------------------------------------------
"""
from atrader import *
import pandas as pd
import numpy as np
from sklearn import svm
import math
from sklearn import preprocessing
import datetime
import torch
from torch import nn
from torch.autograd import Variable
import torchvision.datasets as dsets
import torch.utils.data as Data
import matplotlib.pyplot as plt
import torchvision

# 作为全局变量进行测试

FactorCode = ['ROIC', 'CashToCurrentLiability', 'STDDEV', 'DDNCR', 'PVI', 'EnterpriseFCFPS',
              'PS', 'AdminExpenseTTM', 'FinanExpenseTTM', 'NetIntExpense', 'GrossProfit', 'FY12P',
              'AD', 'TotalAssetGrowRate', 'MA120']
class lstm(nn.Module):
    def __init__(self):
        super(lstm, self).__init__()

        self.rnn = nn.LSTM(
            input_size=len(FactorCode),#x的特征维度
            hidden_size=64,#隐藏层的特征维度,横向
            num_layers=2,#隐层的层数，默认为1,纵向
            batch_first=True, # batch指一次性输入到神经网络中的样本数
            dropout=0.2
        )

        self.out = nn.Linear(64, 1)

    def forward(self, x):
        r_out, (h_n, h_c) = self.rnn(x, None)

        # print(x.shape)
        # print(r_out.shape)

        out = self.out(r_out[:, -1, :])
        # print(r_out[:, -1, :].shape)
        # input()
        return out
LR = 0.01
EPOCH = 3
BATCH_SIZE = 5


# 中位数去极值法
def filter_MAD(df, factor, n=3):
    """
    :param df: 去极值的因子序列
    :param factor: 待去极值的因子
    :param n: 中位数偏差值的上下界倍数
    :return: 经过处理的因子dataframe
    """
    median = df[factor].quantile(0.5)
    new_median = ((df[factor] - median).abs()).quantile(0.5)
    max_range = median + n * new_median
    min_range = median - n * new_median

    for i in range(df.shape[0]):
        if df.loc[i, factor] > max_range:
            df.loc[i, factor] = max_range
        elif df.loc[i, factor] < min_range:
            df.loc[i, factor] = min_range
    return df


def init(context):
    context.SVM = svm.SVC(gamma='scale')
    # 账号设置：设置初始资金为 10000000 元
    set_backtest(initial_cash=10000000, future_cost_fee=1.0, stock_cost_fee=30, margin_rate=1.0, slide_price=0,
                 price_loc=1, deal_type=0, limit_type=0)
    # 注册数据：日频数据
    reg_kdata('day', 1)
    global FactorCode  # 全局单因子代号
    reg_factor(factor=FactorCode)
    print("init 函数, 注册因子为{}".format(FactorCode[0]))
    context.FactorCode = FactorCode  #

    # 超参数设置：
    context.Len = 21   # 时间长度: 当交易日个数小于该事件长度时，跳过该交易日，假设平均每个月 21 个交易日左右  250/12
    context.Num = 0   # 记录当前交易日个数

    # lstm
    context.lstm = lstm()
    context.optimizer = torch.optim.Adam(context.lstm.parameters(), lr=LR)
    context.loss_func = nn.MSELoss()
    context.EPOCH = EPOCH
    context.BATCH_SIZE = BATCH_SIZE

    # 较敏感的超参数，需要调节
    context.upper_pos = 80  # 股票预测收益率的上分位数，高于则买入
    context.down_pos = 20   # 股票预测收益率的下分位数，低于则卖出
    context.cash_rate = 0.6  # 计算可用资金比例的分子，利益大于0的股票越多，比例越小

    # 确保月初调仓
    days = get_trading_days('SSE', '2016-01-01', '2018-09-30')
    months = np.vectorize(lambda x: x.month)(days)
    month_begin = days[pd.Series(months) != pd.Series(months).shift(1)]
    context.month_begin = pd.Series(month_begin).dt.strftime('%Y-%m-%d').tolist()


def on_data(context):
    context.Num = context.Num + 1
    if context.Num < context.Len:  # 如果交易日个数小于Len+1，则进入下一个交易日进行回测
        return
    if datetime.datetime.strftime(context.now, '%Y-%m-%d') not in context.month_begin:  # 调仓频率为月,月初开始调仓
        return

    # 获取数据：
    KData = get_reg_kdata(reg_idx=context.reg_kdata[0], length=context.Len, fill_up=True, df=True)
    FData = get_reg_factor(reg_idx=context.reg_factor[0], target_indices=[x for x in range(300)], length=context.Len,
                           df=True)  # 获取因子数据


    # 特征构建：
    Fcode = context.FactorCode  # 标签不需要代号了

    # 数据存储变量：
    # Close 字段为标签，Fcode 为标签
    FactorData = pd.DataFrame(columns=(['idx', 'benefit'] + Fcode))  # 存储训练特征及标签样本
    FactorDataTest = pd.DataFrame(columns=(['idx'] + Fcode))       # 存储预测特征样本

    # K线数据序号对齐
    tempIdx = KData[KData['time'] == KData['time'][0]]['target_idx'].reset_index(drop=True)

    # 按标的处理数据：
    for i in range(300):
        # 训练特征集及训练标签构建：
        # 临时数据存储变量:
        FactorData0 = pd.DataFrame(np.full([int(context.Len/2), len(Fcode) + 2], np.nan),
            columns=(['idx', 'benefit'] + Fcode))
        # 存储预测特征样本
        FactorDataTest0 = pd.DataFrame(np.full([int(context.Len/2), len(Fcode) + 1], np.nan), columns=(['idx'] + Fcode))

        # 因子数据 序号对齐, 提取当前标的的因子数据
        FData0 = FData[FData['target_idx'] == tempIdx[i]].reset_index(drop=True)

        # 按特征处理数据：
        for FC in context.FactorCode:
            # 提取当前标的中与当前因子FC相同的部分
            FCData = FData0[FData0['factor'] == FC]['value'].reset_index(drop=True)
            #print(FCData.shape)
            #print(FCData[int(context.Len / 2):])
            #print(FCData[:int(context.Len/2)])
            #input()
            FactorData0[FC] = FCData[:int(context.Len/2)]  # 存储上一个月初的股票因子数据

        # 按标签处理数据：
        # 提取当前标的的前一个月的K线面板数据
        close = np.array(KData[KData['target_idx'] == tempIdx[i]]['close'])
        # 计算当前标的在上一个月的收益率
        benefit = (close[-1] - close[int(context.Len/2) - 1]) / close[int(context.Len/2) - 1]

        FactorData0['benefit'] = benefit
        # idx: 建立当前标的在训练样本集中的索引
        FactorData0['idx'] = tempIdx[i]
        # 合并数据：组成训练样本
        FactorData = FactorData.append(FactorData0, ignore_index=True)

        # 预测特征集构建：建立标的索引
        FactorDataTest0['idx'] = tempIdx[i]
        # 按特征处理数据，过程同建立训练特征
        for FC in context.FactorCode:
            FCData = FData0[FData0['factor'] == FC]['value'].reset_index(drop=True)
            #print(FCData.shape)
            #print(FCData[int(context.Len / 2):])
            #print(FCData[:int(context.Len / 2)])
            #input()
            FactorDataTest0[FC] = FCData[int(context.Len/2):].reset_index(drop=True)

        # 合并测试数据
        FactorDataTest = FactorDataTest.append(FactorDataTest0, ignore_index=True)

    """
    训练集和测试集的表头字段如下
    FactorData DataFrame:
    idx  |  benefit |  Factor 1 | Factor 2| ....
    benefit 作为标签，上月初Factor作为特征，此处是单因子测试，只有一个特征
    FactorDataTest DataFrame: 
    idx | Factor 1 | Factor 2 | ...
    本月初的因子作为预测特征
    """

    # 数据清洗：
    FactorData = FactorData.dropna(axis=0, how='any').reset_index(drop=True)  # 清洗数据
    FactorDataTest = FactorDataTest.dropna(axis=0, how='any').reset_index(drop=True)  # 清洗数据

    count1 = FactorData.groupby('idx').count().reset_index()
    remain1 = count1[count1[count1.columns[1]] == int(context.Len / 2)]['idx']
    count2 = FactorDataTest.groupby('idx').count().reset_index()
    remain2 = count2[count2[count2.columns[1]] == int(context.Len / 2)]['idx']
    remain = pd.merge(remain1, remain2, on=['idx']).reset_index(drop=True)
    Idx = remain['idx']  # 剩余标的序号



    FactorData = FactorData[FactorData['idx'].isin(remain['idx'])].reset_index(drop=True)
    FactorDataTest = FactorDataTest[FactorDataTest['idx'].isin(remain['idx'])].reset_index(drop=True)

    #print(count[count.columns[0:2]])

    # 按特征进行预处理
    for Factor in context.FactorCode:
        FactorData = filter_MAD(FactorData, Factor, 5)  # 中位数去极值法
        FactorData[Factor] = preprocessing.scale(FactorData[Factor])  # 标准化

        FactorDataTest = filter_MAD(FactorDataTest, Factor, 5)  # 中位数去极值法
        FactorDataTest[Factor] = preprocessing.scale(FactorDataTest[Factor])  # 标准化

    # print(FactorData.head(1))
    # print(FactorDataTest.head(1))

    # 训练和预测特征构建：# 行（样本数）* 列（特征数）
    X = np.ones([FactorData.shape[0], len(Fcode)])
    Xtest = np.ones([FactorDataTest.shape[0], len(Fcode)])



    # 循环填充特征到numpy数组中
    for i in range(X.shape[1]):
        X[:, i] = FactorData[Fcode[i]]
        Xtest[:, i] = FactorDataTest[Fcode[i]]

    Xtest = np.array([Xtest[i * int(context.Len / 2):(i + 1) * int(context.Len / 2)] for i in range(len(remain))])
    Xtest = torch.from_numpy(Xtest).float()

    # 训练样本的标签，为浮点数的收益率
    Y = FactorData[['idx', 'benefit']]
    Y = Y.groupby('idx').mean().reset_index(drop=True)
    Y = np.array(Y['benefit']).astype(float)

    # print(X.shape)
    # print(X[:2])
    # print(Y)
    # input()

    # 模型训练：
    class trainset(Data.Dataset):
        def __init__(self):
            self.X = X
            self.Y = Y
        def __getitem__(self, index):
            len = int(context.Len/2)
            head = len * index
            tail = len * (index + 1)
            data = self.X[head:tail]
            label = self.Y[index]
            return data, label
        def __len__(self):
            return int(self.X.shape[0]/(context.Len/2))

    train_loader = Data.DataLoader(dataset=trainset(), batch_size=context.BATCH_SIZE, shuffle=True)

    for epoch in range(EPOCH):
        for step, (x, y) in enumerate(train_loader):
            # b_x = Variable(x.view(-1, 28, 28))
            # b_y = Variable(y)
            b_x = x.float()
            b_y = y.float()

            output = context.lstm(b_x)
            loss = context.loss_func(output, b_y)
            context.optimizer.zero_grad()
            loss.backward()
            context.optimizer.step()


    # 预测：
    y = context.lstm(Xtest)
    y = y.detach().numpy().reshape((-1))

    # 交易设置：
    positions = context.account().positions['volume_long']  # 多头持仓数量
    valid_cash = context.account(account_idx=0).cash['valid_cash'][0]  # 可用资金


    # 获取收益率的高分位数和低分位数
    P = context.cash_rate / (sum(y > 0) + 1)  # 设置每只标的可用资金比例 + 1 防止分母为0
    high_return, low_return = np.percentile(y, [context.upper_pos, context.down_pos])


    for i in range(len(Idx)):
        position = positions.iloc[Idx[i]]
        if position == 0 and y[i] > high_return and y[i] > 0 and valid_cash > 0:  # 若预测结果为true(收益率>0)，买入
            # print('开仓')
        # if position == 0 and y[i] > high_return and valid_cash > 0: # 当前无仓，且该股票收益大于高70%分位数，则开仓，买入
            # 开仓数量 + 1防止分母为0
            # print(valid_cash, P, KData['close'][Idx[i]])  # 这里的数目可考虑减少一点，，有时太多有时太少
            Num = int(math.floor(valid_cash * P / 100 / (KData['close'][Idx[i] * 21 + 20] + 1)) * 100)

            # 控制委托量，不要过大或过小,需要保证是100的倍数
            if Num < 1000:
                Num *= 10
            if Num > 100000:
                Num = int(Num / 10)
                Num -= Num % 100
            if Num <= 0:  # 不开仓
                continue

            print("开仓数量为：{}".format(Num))
            order_id = order_volume(account_idx=0, target_idx=int(Idx[i]), volume=Num, side=1, position_effect=1, order_type=2,
                         price=0)  # 指定委托量开仓
            # 对订单号为order_id的委托单设置止损，止损距离10个整数点，触发时，委托的方式用市价委托
            # stop_loss_by_order(target_order_id=order_id, stop_type=1, stop_gap=10, order_type=2)

        elif position > 0 and y[i] < low_return:  #预测结果为false(收益率<0)，卖出
        # elif position > 0 and y[i] < low_return:  # 当前持仓，且该股票收益小于低30%分位数，则平仓，卖出
            # print("平仓")
            order_volume(account_idx=0, target_idx=int(Idx[i]), volume=int(position), side=2, position_effect=2,
                         order_type=2, price=0)  # 指定委托量平仓


if __name__ == '__main__':

    file_path = 'lstm.py'
    block = 'hs300'

    begin_date = '2017-01-01'
    end_date = '2020-01-10'

    strategy_name = 'lstm'

    run_backtest(strategy_name=strategy_name, file_path=file_path,
                 target_list=list(get_code_list('hs300', date=begin_date)['code']),
                 frequency='day', fre_num=1, begin_date=begin_date, end_date=end_date, fq=1)
