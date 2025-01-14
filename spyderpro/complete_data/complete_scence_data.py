import datetime
import copy
import re
from spyderpro.data_requests.scence.place_people_num import PlacePeopleNum
from spyderpro.data_requests.scence.place_people_trend import PlaceTrend
from spyderpro.data_requests.scence.scence_people import ScencePeopleFlow
from spyderpro.pool.threadpool import ThreadPool
from spyderpro.complete_data._complete_data_interface import CompleteDataInterface


class CompleteScenceData(CompleteDataInterface):
    """
    景区缓存数据补全
        各类缓存key格式：
         景区人数： key= "scence:{0}:{1}".format(pid,type_flag),value={"HH:MM:SS":num,.....}
        人流趋势：key = "trend:{pid}".format(pid=region_id) ，value={'00:00:00':rate}
        人流分布： key = "distribution:{0}".format(pide)  value=str([{"lat": centerlat + item.latitude, "lng": centerlon + item.longitude,
                               "count": item.number},......)
    """

    def type_scence_people_num_check(self, scence_type: int, now_time: datetime, cache_time: datetime.timedelta,
                                     time_interval: datetime.timedelta,
                                     time_difference: int) -> bool:
        """
        景区类别完整性数据检查
        :param scence_type: 景区类别，第一类为0，第二类为1
        :param now_time: 此时时间
        :param cache_time: redis中的缓存时间间隔
        :param time_difference: 超时地底线
        :return:
        """
        # 从mysql生产的完整的key模板
        complete_keys_regular = "scence:%d:{scence_type}".format(scence_type=scence_type)
        # 从redis查询的keys模板
        search_regular = "scence:*:{scence_type}".format(scence_type=scence_type)
        sql = "select pid from digitalsmart.scencemanager where type_flag=%d" % scence_type
        # 获取最全的缓存key
        complete_keys = self.get_complete_keys(sql, complete_keys_regular, search_regular)
        check_status = True  # 判断是否需要补漏数据
        for key in complete_keys:
            # 获取缓存的数据
            redis_data = self.redis_worke.hash_get_all(key)
            # 检查数据是否完整
            check_status = self.check_data_complete(list(redis_data.keys()), time_interval)
            if not check_status:
                break

        # 相差time_difference秒必须检查数据完整性
        if self.time_difference(now_time, complete_keys) > time_difference or not check_status:
            result = self._check_scence_people_num_complete(complete_keys, scence_type, cache_time)  # 补漏数据
            return result
        return True

    def type_scence_people_trend_check(self, now_time: datetime, cache_time: datetime.timedelta,
                                       time_interval: datetime.timedelta,
                                       time_difference: int):
        """
        景区类别人流趋势完整性数据检查
        :param now_time:此时时间
        :param cache_time: redis中的缓存时间间隔
        :param time_difference:允许的时间差
        :param time_interval: 缓存数据的时间间隔
        :return:
        """
        complete_keys_regular = "trend:%d"
        search_regular = "trend:*"
        # 缓存key模板
        sql = "select pid from digitalsmart.scencemanager where type_flag=0"
        complete_keys = self.get_complete_keys(sql, complete_keys_regular, search_regular)
        check_status = True  # 判断数据是否完整
        for key in complete_keys:
            # 获取缓存的数据
            redis_data = self.redis_worke.hash_get_all(key)
            # 检查数据是否完整
            check_status = self.check_data_complete(list(redis_data.keys()), time_interval)
            if not check_status:
                break
        if self.time_difference(now_time, complete_keys) > time_difference or not check_status:
            result = self._check_scence_people_trend_complete(complete_keys, cache_time)
            return result
        return True

    def _check_scence_people_num_complete(self, complete_keys: list, scence_type: int,
                                          cache_time: datetime.timedelta) -> bool:
        """
        检查景区人数数据的完整性

        :param scence_type: 第一类景区为0，第二类为1
        :param cache_time:数据时间间隔
        :return:
        """
        # 初始化一整天时间点列表
        init_time = datetime.datetime(2019, 1, 1, 0, 0, 0)  # 初始化时间，时间点以00：00：00为基准点
        now = datetime.datetime.now()
        now_time = str(now.time())
        complete_time = dict()  # 存放一整天的时间点
        if scence_type == 0:  # 生成完整数据的时间序列
            while 1:
                complete_time[str(init_time.time())] = 0  # 键值0表示该时间点还没有数据，1表示有
                init_time = init_time + datetime.timedelta(minutes=5)
                if str(init_time.time()) > now_time:
                    break
        temp_complete_time = dict()
        # x处理缺失数据
        for redis_key in complete_keys:
            if scence_type == 0:
                temp_complete_time = copy.deepcopy(complete_time)
                result = self.redis_worke.hash_get_all(redis_key)
                for time_key in result.keys():
                    time_key = time_key.decode()
                    temp_complete_time.pop(time_key)  # pop已经存在的数据的时间点
            pid = int(re.match('scence:(\d+):\d', redis_key).group(1))  # 提取景区pid
            # 补全缺少的数据
            self._complete_scence_people_num_data(scence_type, redis_key, pid, temp_complete_time, cache_time)

        return True

    def _check_scence_people_trend_complete(self, complete_keys: list, cache_time: datetime.timedelta) -> bool:
        """
        检查景区人数趋势的完整性
        :param complete_keys:缓存key
        :param cache_time: 缓存时间
        :return:
        """

        pool = ThreadPool(max_workers=10)
        # 处理数据缺失问题

        for redis_key in complete_keys:
            self.redis_worke.hash_get_all(redis_key)
            pid = int(re.match('trend:(\d+)', redis_key).group(1))  # 提取景区pid
            sql = "select area from digitalsmart.scencemanager where pid={pid} and type_flag=0".format(pid=pid)
            area = self.mysql_worke.select(sql)[0][0]
            pool.submit(self._complete_scence_people_trend_data, redis_key, area, pid, cache_time)
        pool.run()
        pool.close()
        return True

    def _check_scence_people_distribution_complete(self):
        """
        检查景区人流分布的完整性
        :return:
        """

    def _complete_scence_people_num_data(self, scence_type: int, key: str, pid: int, all_missing_time: dict,
                                         cache_time: datetime.timedelta):
        """
        补全缺失的数据
        :param key: 缓存key
        :param all_missing_time:缺失数据的时间点
        :param pid:景区标识
        :param cache_time: 缓存时间

        :return:
        """
        if len(all_missing_time.keys()) == 0 and scence_type == 0:
            return
        pool = ThreadPool(max_workers=10)
        if scence_type == 0:
            for miss_time in all_missing_time.keys():
                pool.submit(self._fast, scence_type, pid, miss_time)
        else:
            pool.submit(self._fast, scence_type, pid, {})

        pool.run()
        pool.close()
        mapping = dict()  # 存放需要缓存的数据
        # 判断数据对应在哪张表插入
        sql_cmd = "select table_id from digitalsmart.tablemanager where pid={0}".format(pid)
        table_id = self.mysql_worke.select(sql_cmd)[0][0]
        # 插入数据库格式语句
        sql_format = "insert into digitalsmart.historyscenceflow{table_id} (pid, ddate, ttime, num) values ".format(
            table_id=table_id)
        insert_values_list = list()  # 存放插入数据库的数据
        # 并发返回结果， 如果scence_type为0的话，pool.result结果是一个以positioning为元素的列表，否则元素是一个positioning的生成器
        for positioning in pool.result:
            if scence_type == 0:
                if positioning is None:
                    continue
                if positioning.date is not None:
                    insert_values_list.append(str((pid, positioning.date, positioning.detailTime, positioning.num)))
                    mapping[positioning.detailTime] = positioning.num
            else:
                for item in positioning:
                    insert_values_list.append(str((pid, item.date, item.detailTime, item.num)))
                    mapping[item.detailTime] = item.num
        #  缓存追加
        if scence_type == 0:
            self.redis_worke.hash_value_append(key, mapping)
        else:
            self.redis_worke.hashset(key, mapping)
        self.redis_worke.expire(key, cache_time)
        # 插入mysql数据库

        values = ','.join(insert_values_list)
        sql = sql_format + values
        self.mysql_worke.sumbit(sql)

    @staticmethod
    def _fast(scence_type: int, pid: int, miss_time: str):
        """
        网络爬虫，返回数据对象
        :param scence_type:景区类别0，1
        :param pid: 景区id
        :param miss_time:缺失的时间
        :return:
        """

        today = datetime.datetime.today()
        today_ddate = str(today.date())
        if scence_type == 0:
            place = PlacePeopleNum()
            # 统计数据
            response_data = place.get_heatdata_bytime(ddate=today_ddate, date_time=miss_time, region_id=pid)
            if not response_data:
                return None
            positioning = place.count_headdata(response_data, today_ddate, miss_time, pid)


        else:
            scence = ScencePeopleFlow()
            positioning = scence.peopleflow_info(pid, int(today_ddate.replace("-", '')))

        return positioning

    def _complete_scence_people_trend_data(self, key: str, area_name: str, pid: int, cache_time: datetime.timedelta):
        """
         补全数据，这里直接将之前所有的数据写入
        :param key: 缓存key
        :param area_name: 景区名
        :param pid: 景区标识
        :param cache_time: 缓存时间

        :return:
        """
        # 缓存时间
        now = datetime.datetime.today()  # 现在时间
        tomorrow = now + datetime.timedelta(days=1)  # 明天
        today = str(now.date())
        tomorrow_day = str(tomorrow.date())
        trend = PlaceTrend(today, tomorrow_day)
        # 获取这天的趋势数据
        result_objs = trend.get_trend(area_name, pid)
        redis_data = dict()
        insert_values_list: list = list()  # 存放插入数据库的数据
        for obj in result_objs:
            insert_values_list.append(str((pid, obj.ddate, obj.detailtime, obj.index)))
            redis_data[obj.detailtime] = obj.index
        # 缓存
        self.redis_worke.hashset(key, redis_data)
        self.redis_worke.expire(key, cache_time)
        # 插入数据库
        values = ','.join(insert_values_list)
        sql = "insert into digitalsmart.scencetrend (pid, ddate, ttime, rate) VALUES {data}".format(data=values)
        self.mysql_worke.sumbit(sql)
