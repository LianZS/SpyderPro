import requests
import re
import datetime

import json
import csv
import sys
from concurrent import futures

from urllib.parse import urlencode


class Connect:

    def connect(self, par: str, url: str) -> dict:
        """网络连接
        :param par:正则表达式
        :param url:请求链接
        :return json
        """

        data = self.request.get(url=url, headers=self.headers)
        if data.status_code != 200:
            print("%s请求--error:网络出错" % url)
            raise ConnectionError('网络连接中断')
        try:
            if par is not None:
                result = re.findall(par, data.content.decode('gbk'), re.S)[0]
            else:
                result = data.text
        except UnicodeDecodeError:
            result = re.findall(par, data.text, re.S)[0]
        data = json.loads(result)
        assert isinstance(data, (dict, list))
        return data


class ParamTypeCheck():
    @staticmethod
    def type_check(param, param_type):
        """
        参数类型检查
        :rtype:
        :param param:
        :param param_type:
        :return:
        """
        assert isinstance(param, param_type), "the type of param is wrong"


class PlaceInterface(Connect, ParamTypeCheck):
    instance = None
    instance_flag: bool = False

    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    # 获取所有省份
    def get_allprovince(self) -> list:
        """
        获取所有省份
        :return: list
        """
        href = "https://heat.qq.com/api/getAllProvince.php?sub_domain="
        par: str = None
        g = self.connect(par, href)
        data = [value["province"] for value in g]
        return data

    # 所有城市
    def get_allcity(self, province: str) -> list:
        """
        获取省份下所有城市
        :param province: 省份名
        :return: list[{"province": , "city":}，，]
        """
        # 这里不需要quote中文转url，因为后面的urlencode自动会转

        parameter = {
            "province": province,
            "sub_domain": ''
        }
        href = "https://heat.qq.com/api/getCitysByProvince.php?" + urlencode(parameter)
        par: str = None
        g = self.connect(par, href)
        results = [{"province": province, "city": value["city"]} for value in g]
        return results

    def get_regions_bycity(self, province: str, city: str) -> list:
        """
        获取城市下所有地区信息标识，关键id

        :type province: str
        :type city:str
        :param province:省份
        :param city:城市
        :return  list[{"place": , "id": },,,,]
        """
        self.type_check(province, str)
        self.type_check(city, str)
        parameter = {
            'province': province,
            'city': city,
            'sub_domain': ''
        }

        href = "https://heat.qq.com/api/getRegionsByCity.php?" + urlencode(parameter)

        par: str = None
        g = self.connect(par, href)
        datalist = list()
        for value in g:
            placename = value['name']  # 地点
            placeid = value["id"]  # id
            dic = {"place": placename, "id": placeid}
            datalist.append(dic)
        return datalist
        # range表示数据间隔，最小1,region_name是地点名字,id是景区pid


class PlaceFlow(PlaceInterface):
    """
    获取地区人口分布情况数据
    """

    def __init__(self, user_agent: str = None):

        if not PlaceFlow.instance_flag:
            PlaceFlow.instance_flag = True
            self.headers = dict()
            if user_agent is None:
                self.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 ' \
                                             '(KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36'

            else:
                self.headers['User-Agent'] = user_agent
            self.headers['Host'] = 'heat.qq.com'

            self.request = requests.Session()

    def request_heatdata(self, url: str):
        """
        网络请求
        :param url:
        :return:json
        """
        response = self.request.get(url=url, headers=self.headers)
        g = json.loads(response.text)
        return g

    def __get_heatdata_bytime(self, date: str, datetim: str, region_id: int):
        # self.type_check(region_id, int)
        paramer = {
            'region_id': region_id,
            'datetime': "".join([date, ' ', datetim]),
            'sub_domain': ''
        }

        url = "https://heat.qq.com/api/getHeatDataByTime.php?" + urlencode(paramer)
        g = self.request_heatdata(url)
        return g

    def count_headdata(self, date: str, datetim: str, region_id: int):
        """
        某一时刻的人数有多少
        :param date:日期：格式yyyy-mm-dd
        :param datetim:时间：格式hh:MM:SS
        :param region_id:地区唯一表示
        :return:总人数
        """
        g = self.__get_heatdata_bytime(date, datetim, region_id)
        count = sum(g.values())  # 总人数
        data = {"date": "".join([date, ' ', datetim]), "num": count}

        return data

    def complete_heatdata(self, date: str, datetim: str, region_id: int):
        """
           某一时刻的人数以及分布情况
           :param date:日期：格式yyyy-mm-dd
           :param datetime:时间：格式hh:MM:SS
           :param region_id:地区唯一表示
           :return:dict格式：{"lat": lat, "lng": lng, "num": num}->与中心经纬度的距离与相应人数
           """
        g = self.__get_heatdata_bytime(date, datetim, region_id)
        coords = map(self.deal_coordinates, g.keys())  # 围绕中心经纬度加减向四周扩展
        numlist = iter(g.values())
        for xy, num in zip(coords, numlist):
            lat = xy[0]
            lng = xy[1]
            yield {"lat": lat, "lng": lng, "num": num}

    @staticmethod
    def deal_coordinates(coord):
        return eval(coord)


def get_count(name, region_id):
    executor = futures.ThreadPoolExecutor(max_workers=2)
    p = PlaceFlow()
    datelist = dateiter(region_id)
    # f = open('/data/Flow/static/' + name + ".csv", 'a+', newline="")
    # w = csv.writer(f)
    # print(f)

    tasks = executor.map(lambda x: p.count_headdata(x[0], x[1]
                                                    , x[2]), datelist)
    for t in tasks:
        print(t)
    # for x in datelist:
    #     result = p.count_headdata(str(x[0]), str(x[1]), x[2])
    #
    #     num = result['num']
    #     if num == 0:
    #         continue
    #     date = result['date']
    # write(w, date, num)
    # f.flush()


def write(writeobj, date, num):
    writeobj.writerow([date, num])


def dateiter(region_id):
    inittime = datetime.datetime(2017, 1, 1, 0, 0, 0)
    timedelta = datetime.timedelta(minutes=5)
    while 1:
        inittime = inittime + timedelta
        if inittime.year == 2019 and inittime.month == 6 and inittime.day == 28:
            break
        yield str(inittime.date()), str(inittime.time()), region_id


if __name__ == "__main__":
    file = open("/Users/darkmoon/Project/SpyderPr/spyderpro/testdata/region_id.csv", "r")
    r = csv.reader(file)
    r.__next__()
    flag_count = 0
    for item in r:
        flag_count += 1
        if flag_count <= 200:
            continue
        name = item[0]
        pid = item[1]
        print(name)
        get_count(name, pid)