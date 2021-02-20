from django.shortcuts import render
from django.http import HttpResponse
from django import forms
from django.forms import fields
from sqlalchemy import create_engine
from chinese_calendar import is_holiday
import datetime
import math
import requests
import json
import numpy as np
import pandas as pd
import re


# Create your views here.
# def parameter(request):
#     return render(request, "fbaInfo/index.html")

# 定义获取库存，在途量大小列表，在途量到达仓库的时间列表
def get_stock(sku, site):
    # url = 'http://scan.surces.com/v2/AmazonProductAsin/get_sku_batches/{}/{}'.format(sku, site)
    url = 'http://scan.surces.com/v2/AmazonProductAsin/get_sku_batches/{}/{}'.format(sku, site)
    req = requests.get(url)
    obj = req.content.decode('utf-8')
    res = json.loads(obj)
    # 有无数据
    code = int(res.get("code"))
    if code == 200:
        # 库存数量
        current_stock = int(res.get("Inventory"))
        # 批次数据列表
        data_list = res.get("data")[sku]
        num_list = []
        by_time = []
        channel_time = []
        state_list = []
        channel_list = []
        delivery_list = []
        batches_time = []
        for dic in data_list:
            state_list.append(dic["state"])
            channel_list.append(dic["channel"])
            num_list.append(dic["amount"])
            by_time.append(dic["buy_time"])
            channel_time.append(dic["waybill_o_id"])
            delivery_list.append(dic["delivery_days"])
            batches_time.append(dic["batches"])
        intransit_num = []
        intransit_days = []
        for index, x in enumerate(state_list):
            if (x is None or x is '' or "上架检测已签收" not in x) and num_list[index] != "0":
                if by_time[index] is None:
                    month = int(list(re.findall("\d+", channel_time[index]))[1])
                    day = int(list(re.findall("\d+", channel_time[index]))[2])
                    total_days = int(list(re.findall("\d+", delivery_list[index]))[1])
                    if month <= datetime.datetime.now().month:
                        future_time = datetime.date(datetime.datetime.now().year, month, day) + datetime.timedelta(
                            days=total_days + 3)
                    else:
                        future_time = datetime.date(datetime.datetime.now().year - 1, month, day) + datetime.timedelta(
                            days=total_days + 3)
                elif by_time[index] != "0000-00-00" and (
                        int(datetime.datetime.now().year) - int(by_time[index][0:4]) <= 1):
                    if channel_time[index] is None:
                        if channel_list[index] != "":
                            total_days = int(list(re.findall("\d+", delivery_list[index]))[1])
                            future_time = datetime.datetime.now().date() + datetime.timedelta(days=total_days + 5)
                        else:
                            if int((datetime.datetime.strptime(by_time[index], '%Y-%m-%d').date() + datetime.timedelta(
                                    days=65) - datetime.datetime.now().date()).days) <= 30:
                                future_time = datetime.datetime.now().date() + datetime.timedelta(days=50)
                            else:
                                future_time = datetime.datetime.strptime(by_time[index], '%Y-%m-%d').date() + \
                                              datetime.timedelta(days=65)
                    else:
                        month = int(list(re.findall("\d+", channel_time[index]))[1])
                        day = int(list(re.findall("\d+", channel_time[index]))[2])
                        if delivery_list[index] == "":
                            total_days = 95
                        else:
                            total_days = int(list(re.findall("\d+", delivery_list[index]))[1])
                        if month <= datetime.datetime.now().month:
                            future_time = datetime.date(datetime.datetime.now().year, month, day) + datetime.timedelta(
                                days=total_days + 3)
                        else:
                            future_time = datetime.date(datetime.datetime.now().year - 1, month,
                                                        day) + datetime.timedelta(
                                days=total_days + 3)

                else:
                    batch_day = int(batches_time[index][-6:-4])
                    batch_month = int(batches_time[index][-8:-6])
                    # batch_year = int(batches_time[index][-12:--8])
                    if batch_month <= datetime.datetime.now().month:
                        future_time = datetime.date(datetime.datetime.now().year, batch_month,
                                                    batch_day) + datetime.timedelta(
                            days=65)
                    else:
                        future_time = datetime.date(datetime.datetime.now().year - 1, batch_month,
                                                    batch_day) + datetime.timedelta(
                            days=65)
                # print(index, future_time, sep=",")
                last_time = (future_time - datetime.datetime.now().date()).days
                if int(last_time) > 0:
                    intransit_days.append(last_time)
                else:
                    intransit_days.append(5)
                intransit_num.append(int(num_list[index]))
            else:
                pass
        intransit_num = list(np.array(intransit_num)[np.argsort(intransit_days)])
        intransit_days.sort()
        return current_stock, intransit_num, intransit_days, code
    else:
        return 0, [], [], code


# 从数据库获取当前sku最近的7天的销量的平均值：
def get_quantity(sku, site):
    engine = create_engine('mysql+pymysql://analyse:analyse@192.168.7.83:3306/adan')
    if site is None or site == "" or site == "US":
        sql = 'select ROUND(sum(quantity)/count(distinct(purchase_date)),0) quantity from sku_orders where sku = "{}" '\
              'and purchase_date between (select date_sub(max(purchase_date)-2, interval 14 day) from sku_orders) and '\
              '(select date_sub(max(purchase_date)-2, interval 0 day) from sku_orders);'.format(sku)
    else:
        sql = 'select ROUND(sum(quantity)/count(distinct(purchase_date)),0) quantity from sku_orders where sku = "{}"' \
              'and `name` like "%%{}" and purchase_date between (select date_sub(max(purchase_date)-2, interval 14 day)'\
              'from sku_orders) and (select date_sub(max(purchase_date)-2, interval 0 day) from sku_orders);'.format(sku, site)
    current_sales = pd.read_sql_query(sql, engine)["quantity"][0]
    return current_sales


# 定义计算经过时间、最后总库存、最后的当前库的函数
count = 0
que_list = []


def timeandnum(current_stock, current_sales, intransit_days, intransit_num, count):
    # 当前库存能够维持的天数
    if current_stock % current_sales == 0:
        hold_time = int(current_stock / current_sales)
    else:
        hold_time = math.ceil(current_stock / current_sales)
    # print(hold_time)
    # 当前库存消耗完之前的总库存first_stock
    num = 0
    for elm in intransit_days:
        if elm <= hold_time:
            num = num + 1
    # 在途量到达仓库时间的三种情况
    if num == len(intransit_days):
        first_stock = hold_time * (current_stock - current_sales) - hold_time * (hold_time - 1) * current_sales / 2
        for index in range(len(intransit_days)):
            first_stock = int(first_stock + (hold_time - intransit_days[index] + 1) * intransit_num[index])
        new_stocks = sum(intransit_num) + (current_stock - current_sales) - (hold_time - 1) * current_sales
        return count, hold_time, first_stock, new_stocks, que_list

    elif num == 0:
        if current_stock % current_sales == 0:
            first_stock = hold_time * (current_stock - current_sales) - hold_time * (hold_time - 1) * current_sales / 2
            que = intransit_days[0] - hold_time
        else:
            first_stock = int((hold_time - 1) * (current_stock - current_sales) - (hold_time - 1) * (
                    hold_time - 2) * current_sales / 2)
            que = intransit_days[0] - hold_time + 1
        new_stocks = intransit_num[0]
        hold_time = intransit_days[0]
        new_days = []
        for i in intransit_days[1:]:
            new_days.append(i - intransit_days[0])
        new_num = intransit_num[1:]
        # print("第{}次可能存在缺货{}天".format(count,que))
        que_list.append("第{}次到货之前可能缺货{}天".format(count + 1, que))
        count = count + 1
        hold_time = hold_time + list(timeandnum(new_stocks, current_sales, new_days, new_num, count))[1]
        first_stock = first_stock + new_stocks + list(timeandnum(new_stocks, current_sales, new_days, new_num, count))[
            2]
        new_stocks = list(timeandnum(new_stocks, current_sales, new_days, new_num, count))[3]
        return count, hold_time, first_stock, new_stocks, que_list

    else:
        first_stock = hold_time * (current_stock - current_sales) - hold_time * (hold_time - 1) * current_sales / 2
        for index in range(num):
            first_stock = int(first_stock + (hold_time - intransit_days[index] + 1) * intransit_num[index])
        new_stocks = sum(intransit_num[0:num]) + (current_stock - current_sales) - (hold_time - 1) * current_sales
        count = count + num
        new_days = []
        for i in intransit_days[num:]:
            new_days.append(i - hold_time)
        new_num = intransit_num[num:]
        hold_time = hold_time + list(timeandnum(new_stocks, current_sales, new_days, new_num, count))[1]
        first_stock = first_stock + list(timeandnum(new_stocks, current_sales, new_days, new_num, count))[2]
        new_stocks = list(timeandnum(new_stocks, current_sales, new_days, new_num, count))[3]
        return count, hold_time, first_stock, new_stocks, que_list


#  判断是否为工作日函数
def holiday(res_date):  # date = datetime.date(2020, 10, 7)
    while True:
        if is_holiday(res_date):
            res_date += datetime.timedelta(days=-1)
        else:
            break
    return res_date


class TestForm(forms.Form):
    site = fields.ChoiceField(
        choices=[(1, "  "), (2, "US"), (3, "UK"), (4, "FR"), (5, "DE"), (6, "ES"), (6, "IT"), ],  # 单选下拉框
        initial=2
    )


def parameter(request):
    if request.method == "GET":
        site_list = ["", "US", "UK", "FR", "DE", "ES", "IT"]
        # site_list = TestForm()
        return render(request, "fbaInfo/index.html", context={"site_list": site_list})
    if request.method == "POST":
        que_list.clear()
        site_list = ["", "US", "UK", "FR", "DE", "ES", "IT"]
        # site_list = TestForm()
        """
        开始判断并返回页面
        """
        # 判断输入是否合规
        # print(int(get_quantity(request.POST.get('number1'), request.POST.get('number2'))))
        # print(get_stock(request.POST.get('number1'), request.POST.get('number2')))
        # print(request.POST.get('number1'), request.POST.get('number2'))
        # sku输入错误
        if request.POST.get('number1') == "" or " " in request.POST.get('number1'):
            err = "sku为空or包含空格"
            return render(request, "fbaInfo/None.html", context={"err": err})
        # 返回400
        elif get_stock(request.POST.get('number1'), request.POST.get('number2'))[3] == 400:
            err = "sku与站点信息不匹配，查不到库存及批次信息"
            return render(request, "fbaInfo/None.html", context={"err": err})
        # 销量为0
        elif get_quantity(request.POST.get('number1'), request.POST.get('number2')) is None:
            err = "sku销量为空"
            return render(request, "fbaInfo/None.html", context={"err": err})
        # 库存和在途批次都为0
        elif list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0] == 0 \
                and len(list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[1]) == 0:
            err = "库存和在途批次都为0，尽快补货"
            return render(request, "fbaInfo/None.html", context={"err": err})
        # 销量不为0，库存或批次至少有一个不为0
        else:
            length = 90
            sell_through = 3
            # 海陆空运时间
            ocean_time = 40
            land_time = 30
            air_time = 20
            # site_list = ["", "US", "UK", "FR", "DE", "ES", "IT"]
            # 输入的sku,site
            sku = request.POST.get('number1')
            site = request.POST.get('number2')
            current_sales = int(get_quantity(request.POST.get('number1'), request.POST.get('number2')))
            # 库存为0，在途批次不为0
            if list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0] == 0 \
                    and len(list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[1]) != 0:
                current_stock = 0
                intransit_num = list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[1]
                intransit_days = list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[2]
                print(sku, site, current_sales, current_stock, intransit_num, intransit_days)
                past_time = int(list(timeandnum(current_stock, current_sales, intransit_days, intransit_num, count))[1])
                sum_stock = int(list(timeandnum(current_stock, current_sales, intransit_days, intransit_num, count))[2])
                future_stock = list(timeandnum(current_stock, current_sales, intransit_days, intransit_num, count))[3]
                xx = list(timeandnum(current_stock, current_sales, intransit_days, intransit_num, count))[4]
                lost = []
                for x in xx:
                    if x not in lost:
                        lost.append(x)
            # 库存不为0，在途批次为0
            elif list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0] != 0 \
                    and len(list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[1]) == 0:
                if (site == "FR" or site == "DE" or site == "ES" or site == "IT") and \
                        list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0] > 4:
                    current_stock = int(
                        list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0] / 4)
                else:
                    current_stock = list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0]
                intransit_num = []
                intransit_days = []
                print(sku, site, current_sales, current_stock, intransit_num, intransit_days)
                past_time = 0
                sum_stock = 0
                future_stock = current_stock
                lost = []
            # 库存和在途批次都不为0
            else:
                if (site == "FR" or site == "DE" or site == "ES" or site == "IT") and \
                        list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0] > 4:
                    current_stock = int(
                        list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0] / 4)
                else:
                    current_stock = list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[0]
                intransit_num = list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[1]
                intransit_days = list(get_stock(request.POST.get('number1'), request.POST.get('number2')))[2]
                print(sku, site, current_sales, current_stock, intransit_num, intransit_days)
                past_time = int(list(timeandnum(current_stock, current_sales, intransit_days, intransit_num, count))[1])
                sum_stock = int(list(timeandnum(current_stock, current_sales, intransit_days, intransit_num, count))[2])
                future_stock = list(timeandnum(current_stock, current_sales, intransit_days, intransit_num, count))[3]
                xx = list(timeandnum(current_stock, current_sales, intransit_days, intransit_num, count))[4]
                lost = []
                for x in xx:
                    if x not in lost:
                        lost.append(x)
            # 未来库存维持时间和未来总库存
            if future_stock % current_sales == 0:
                keep_time = int(future_stock / current_sales)
                inventory = (future_stock - current_sales + 0) * keep_time / 2
            else:
                keep_time = math.ceil(future_stock / current_sales)
                inventory = (future_stock - current_sales) * (keep_time - 1) - (keep_time - 1) * (
                        keep_time - 2) * current_sales / 2
            # 总维持时间与90天的对比
            if keep_time + past_time > length:
                # 此时的售出率
                sell_th = round((current_sales * length) / ((sum_stock + (
                        (future_stock - current_sales) * (keep_time - (keep_time + past_time - length)) - (
                        keep_time - (keep_time + past_time - length)) * (keep_time - (
                        keep_time + past_time - length) - 1) * current_sales / 2)) / length), 4)
                result1 = "所有批次维持时间大于90天，无需补货"
                result2 = "在{}时必须到货以便维持之后的库存，到货量根据具体运营情况而定" \
                    .format(str(datetime.datetime.now().date() + datetime.timedelta(days=keep_time + past_time)))
                result3 = "此时的售出率为：{}".format(sell_th)
                result4 = keep_time + past_time
                result5 = length - (keep_time + past_time)
                return render(request, "fbaInfo/index.html",
                              context={'data1': past_time, "data2": sum_stock, "data3": future_stock,
                                       "data4": tuple(lost),
                                       "result1": result1, "result2": result2, "result3": result3,
                                       "result4": result4,
                                       "result5": result5, "condition1": current_sales, "condition2": current_stock,
                                       "condition3": intransit_num, "condition4": intransit_days,
                                       "condition5": sku, "condition6": site, "site_list": site_list})
            elif keep_time + past_time == length:
                sell_th = round((current_sales * length) / ((sum_stock + inventory) / length), 4)
                result1 = "所有批次维持时间等于90天，无需补货"
                result2 = "在{}天时必须到货以便维持之后的库存，到货量根据具体运营情况而定" \
                    .format(str(datetime.datetime.now().date() + datetime.timedelta(days=length + 1)))
                result3 = "此时的售出率为：{}".format(sell_th)
                result4 = keep_time + past_time
                result5 = length - (keep_time + past_time)
                return render(request, "fbaInfo/index.html",
                              context={'data1': past_time, "data2": sum_stock, "data3": future_stock,
                                       "data4": tuple(lost),
                                       "result1": result1, "result2": result2, "result3": result3,
                                       "result4": result4,
                                       "result5": result5, "condition1": current_sales, "condition2": current_stock,
                                       "condition3": intransit_num, "condition4": intransit_days,
                                       "condition5": sku, "condition6": site, "site_list": site_list})
            else:
                result1 = "所有批次维持时间小于90天，需要补货"
                result2 = "所有批次维持时间小于90天，需要补货"
                result3 = "所有批次维持时间小于90天，需要补货"
                result4 = keep_time + past_time
                result5 = length - (keep_time + past_time)
                # 需要补货时根据售罄率计算得到补货之后的最大的库存总量
                # print(current_sales, current_stock, length, sum_stock)
                last_stock = int(current_sales * length / sell_through * length - sum_stock)
                print("根据售罄率的最大库存总量：%d" % last_stock)
                # 根据每天的销售，库存维持到91天时刚好为零时的最小库存量
                limit_stock = int((length - keep_time - past_time - 1) * current_sales * (
                        length - keep_time - past_time) / 2 + current_sales * (length - keep_time - past_time))
                print("为零时的最小库存量：%d" % limit_stock)
                # 最大的库存总量小于最小库存时：
                if limit_stock >= last_stock:
                    sell_th = (current_sales * length) / ((sum_stock + limit_stock) / length)
                    # 最小的到货数量
                    limit_quantity = (length - keep_time - past_time - 1) * current_sales + current_sales
                    out1 = "90天的售出率会小于或等于{}".format(sell_through)
                    out2 = "此时的售出率为：{}".format(sell_th)
                    out3 = "应在第{}天时到货{},且在第{}天时再次到货以维持库存".format(keep_time + past_time, limit_quantity, length + 1)
                    # 补货方法
                    # 判断keep_time + past_time时间与海、陆、空运时间的比较
                    if keep_time + past_time < air_time:
                        show1 = "空运"
                        show2 = ["库存维持时间过短，尽快补货"]
                        show3 = [limit_quantity]
                        show4 = ["库存维持时间过短，尽快补货"]
                        show5 = [limit_quantity]
                        show6 = ["库存维持时间过短，尽快补货"]
                        show7 = [limit_quantity]
                    elif air_time <= keep_time + past_time < land_time:
                        show1 = "空运"
                        x = keep_time + past_time - air_time  # x天之后空运下单，补货日期
                        time1 = datetime.datetime.now().date() + datetime.timedelta(days=x)  # 补货日期
                        show2 = [str(holiday(time1))]
                        show3 = [limit_quantity]
                        show4 = ["库存维持时间较短，不建议采用陆运"]
                        show5 = ["库存维持时间较短，不建议采用陆运"]
                        show6 = ["库存维持时间较短，不建议采用海运"]
                        show7 = ["库存维持时间较短，不建议采用海运"]
                    elif land_time <= keep_time + past_time < ocean_time:
                        show1 = "空运、陆运"
                        x = keep_time + past_time - air_time  # x天之后空运下单，补货日期
                        y = keep_time + past_time - land_time  # y天之后陆运下单，补货日期
                        time1 = datetime.datetime.now().date() + datetime.timedelta(days=x)  # 补货日期
                        show2 = [str(holiday(time1))]
                        show3 = [limit_quantity]
                        time2 = datetime.datetime.now().date() + datetime.timedelta(days=y)  # 补货日期
                        show4 = [str(holiday(time2))]
                        show5 = [limit_quantity]
                        show6 = ["库存维持时间较短，不建议采用海运"]
                        show7 = ["库存维持时间较短，不建议采用海运"]
                    else:
                        show1 = "空运、陆运、海运"
                        x = keep_time + past_time - air_time  # x天之后空运下单，补货日期
                        y = keep_time + past_time - land_time  # y天之后陆运下单，补货日期
                        z = keep_time + past_time - ocean_time  # z天之后海运下单，补货日期
                        time1 = datetime.datetime.now().date() + datetime.timedelta(days=x)  # 补货日期
                        show2 = [str(holiday(time1))]
                        show3 = [limit_quantity]
                        time2 = datetime.datetime.now().date() + datetime.timedelta(days=y)  # 补货日期
                        show4 = [str(holiday(time2))]
                        show5 = [limit_quantity]
                        time3 = datetime.datetime.now().date() + datetime.timedelta(days=z)  # 补货日期
                        show6 = [str(holiday(time3))]
                        show7 = [limit_quantity]
                    elm1 = zip(show2, show3)
                    elm2 = zip(show4, show5)
                    elm3 = zip(show6, show7)
                    return render(request, "fbaInfo/index.html",
                                  context={'data1': past_time, "data2": sum_stock, "data3": future_stock,
                                           "data4": tuple(lost),
                                           "result1": result1, "result2": result2, "result3": result3,
                                           "result4": result4,
                                           "result5": result5, "condition1": current_sales,
                                           "condition2": current_stock,
                                           "condition3": intransit_num, "condition4": intransit_days,
                                           "condition5": sku, "condition6": site, "site_list": site_list,
                                           "out1": out1, "out2": out2, "out3": out3, "last_stock": last_stock,
                                           "limit_stock": limit_stock, "limit_quantity": limit_quantity,
                                           "show1": show1,
                                           "show2": show2, "show3": show3, "show4": show4, "show5": show5,
                                           "show6": show6,
                                           "show7": show7, "elm1": elm1, "elm2": elm2, "elm3": elm3})
                else:
                    # 最大的到货数量
                    max_quantity = last_stock / (length - keep_time - past_time) + (
                            (length - keep_time - past_time - 1) * current_sales) / 2
                    print("最大的到货数量: %d" % max_quantity)
                    # 最小的到货数量
                    limit_quantity = (length - keep_time - past_time - 1) * current_sales + current_sales
                    print("最小的到货数量: %d" % limit_quantity)
                    # 最大的提前天数(进一次货的前提下)
                    day = math.floor((last_stock - limit_stock) / limit_quantity)
                    print("最大提前天数：%d" % day)
                    time_list = []
                    num_list = []
                    # another_time_list = []
                    # 到货时间列表及日期列表及时间周期外的到货时间点
                    for i in range(day + 1):
                        early_time = keep_time + past_time - i
                        early_num = math.floor((last_stock + current_sales * (length - keep_time - past_time) * (
                                length - keep_time - past_time - 1) / 2) / (length - keep_time - past_time + i))
                        # another_time = keep_time + past_time + math.ceil(early_num / current_sales)
                        if early_time >= 20:
                            time_list.append(early_time)
                            num_list.append(early_num)
                            # another_time_list.append(another_time)
                        else:
                            pass
                    out1 = time_list[::-1]
                    # print(out1)
                    out2 = num_list[::-1]
                    # out3 = another_time_list[::-1]
                    out3 = "其他到货时间列表"
                    if len(out1) > 0:
                        last = out1[-1]
                    else:
                        last = 0
                    # 将时间和数量列表转为字典
                    res_dict = {k: v for k, v in zip(out1, out2)}
                    res_dict2 = {key: value for key, value in res_dict.items() if key >= land_time}
                    res_dict3 = {key: value for key, value in res_dict.items() if key >= ocean_time}
                    # long = len(out1)
                    # 补货方法
                    # 判断时间列表的长度；根据时间列表的最大值与最小值确定补货的运输方式；最后输出进货时间区间以及进货数量；
                    if len(out1) == 0:
                        # long = len(out1)
                        show1 = "空运"
                        show2 = ["库存维持时间过短，尽快补货"]
                        show3 = [limit_quantity]
                        show4 = ["库存维持时间过短，尽快补货"]
                        show5 = [limit_quantity]
                        show6 = ["库存维持时间过短，尽快补货"]
                        show7 = [limit_quantity]
                    elif len(out1) == 1:
                        # long =len(out1)
                        if out1[0] < land_time:
                            show1 = "空运"
                            time1 = datetime.datetime.now().date() + datetime.timedelta(days=out1[0] - air_time)
                            show2 = [str(holiday(time1))]
                            show3 = [out2[0]]
                            show4 = ["库存维持时间较短，不建议采用陆运"]
                            show5 = ["库存维持时间较短，不建议采用陆运"]
                            show6 = ["库存维持时间较短，不建议采用海运"]
                            show7 = ["库存维持时间较短，不建议采用海运"]
                        elif land_time <= out1[0] < ocean_time:
                            show1 = "空运、陆运"
                            time1 = datetime.datetime.now().date() + datetime.timedelta(days=out1[0] - air_time)
                            show2 = [str(holiday(time1))]
                            show3 = [out2[0]]
                            time2 = datetime.datetime.now().date() + datetime.timedelta(days=out1[0] - land_time)
                            show4 = [str(holiday(time2))]
                            show5 = [out2[0]]
                            show6 = ["库存维持时间较短，不建议采用海运"]
                            show7 = ["库存维持时间较短，不建议采用海运"]
                        else:
                            show1 = "空运、陆运、海运"
                            time1 = datetime.datetime.now().date() + datetime.timedelta(days=out1[0] - air_time)
                            show2 = [str(holiday(time1))]
                            show3 = [out2[0]]
                            time2 = datetime.datetime.now().date() + datetime.timedelta(days=out1[0] - land_time)
                            show4 = [str(holiday(time2))]
                            show5 = [out2[0]]
                            time3 = datetime.datetime.now().date() + datetime.timedelta(days=out1[0] - ocean_time)
                            show6 = [str(holiday(time3))]
                            show7 = [out2[0]]
                    # elif 2 <= len(out1):
                    else:
                        # long = len(out1)
                        if last <= land_time:
                            show1 = "空运"
                            for time in list(res_dict.keys()):
                                if is_holiday(
                                        datetime.datetime.now().date() + datetime.timedelta(days=time - air_time)):
                                    res_dict.pop(time)
                            show2 = [str(j) for j in
                                     [datetime.datetime.now().date() + datetime.timedelta(days=i - air_time) for i in
                                      list(res_dict.keys())]]
                            show3 = list(res_dict.values())
                            show4 = ["库存维持时间较短，不建议采用陆运"]
                            show5 = ["库存维持时间较短，不建议采用陆运"]
                            show6 = ["库存维持时间较短，不建议采用海运"]
                            show7 = ["库存维持时间较短，不建议采用海运"]
                        elif land_time < last <= ocean_time:
                            show1 = "空运、陆运"
                            for time in list(res_dict.keys()):
                                if is_holiday(datetime.datetime.now().date() + datetime.timedelta(days=time - air_time)):
                                    res_dict.pop(time)
                            for time in list(res_dict2.keys()):
                                if is_holiday(datetime.datetime.now().date() + datetime.timedelta(days=time - land_time)):
                                    res_dict2.pop(time)
                            show2 = [str(j) for j in
                                         [datetime.datetime.now().date() + datetime.timedelta(days=i - air_time) for i
                                          in list(res_dict.keys())]]
                            show3 = list(res_dict.values())
                            show4 = [str(j) for j in
                                         [datetime.datetime.now().date() + datetime.timedelta(days=i - land_time) for i
                                          in list(res_dict2.keys())]]
                            show5 = list(res_dict2.values())
                            show6 = ["库存维持时间较短，不建议采用海运"]
                            show7 = ["库存维持时间较短，不建议采用海运"]
                        else:
                            show1 = "空运、陆运、海运"
                            for time in list(res_dict.keys()):
                                if is_holiday(datetime.datetime.now().date() + datetime.timedelta(days=time - air_time)):
                                    res_dict.pop(time)
                            for time in list(res_dict2.keys()):
                                if is_holiday(datetime.datetime.now().date() + datetime.timedelta(days=time - land_time)):
                                    res_dict2.pop(time)
                            for time in list(res_dict3.keys()):
                                if is_holiday(datetime.datetime.now().date() + datetime.timedelta(days=time - land_time)):
                                    res_dict3.pop(time)
                            show2 = [str(j) for j in
                                     [datetime.datetime.now().date() + datetime.timedelta(days=i - air_time) for i in
                                      list(res_dict.keys())]]
                            show3 = list(res_dict.values())
                            show4 = [str(j) for j in
                                     [datetime.datetime.now().date() + datetime.timedelta(days=i - land_time) for i in
                                      list(res_dict2.keys())]]
                            show5 = list(res_dict2.values())
                            show6 = [str(j) for j in
                                     [datetime.datetime.now().date() + datetime.timedelta(days=i - ocean_time) for i in
                                      list(res_dict3.keys())]]
                            # print(show6)
                            show7 = list(res_dict3.values())
                            # print(show7)
                    elm1 = zip(show2, show3)
                    elm2 = zip(show4, show5)
                    elm3 = zip(show6, show7)
                    return render(request, "fbaInfo/index.html",
                                  context={'data1': past_time, "data2": sum_stock, "data3": future_stock,
                                           "data4": tuple(lost),
                                           "result1": result1, "result2": result2, "result3": result3,
                                           "result4": result4,
                                           "result5": result5, "condition1": current_sales,
                                           "condition2": current_stock,
                                           "condition3": intransit_num, "condition4": intransit_days,
                                           "condition5": sku, "condition6": site, "site_list": site_list,
                                           "out1": out1, "out2": out2, "out3": out3, "last_stock": last_stock,
                                           "limit_stock": limit_stock, "limit_quantity": limit_quantity,
                                           "show1": show1,
                                           "show2": show2, "show3": show3, "show4": show4, "show5": show5,
                                           "show6": show6,
                                           "show7": show7, "last": last, "air_time": air_time,
                                           "land_time": land_time,
                                           "ocean_time": ocean_time, "elm1": elm1, "elm2": elm2, "elm3": elm3})
