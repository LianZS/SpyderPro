import datetime
from threading import Thread, Semaphore
from concurrent.futures import ThreadPoolExecutor
from pymysql.connections import Connection
from spyderpro.managerfunction.connect import ConnectPool
from spyderpro.function.trafficfunction.traffic import Traffic
from setting import *


class ManagerTraffic(Traffic):
    def __init__(self):
        self.taskSemaphore = Semaphore(5)  # 任务并发锁头🔒
        self.pidLock = Semaphore(1)  # 数据锁🔒

    def manager_city_traffic(self):
        """
        获取城市实时交通拥堵情况并写入数据库,半小时执行一次
        :return:
        """
        pool = ConnectPool(max_workers=10)
        sql = "select pid from digitalsmart.citymanager"
        data = pool.select(sql)
        thread_pool = ThreadPoolExecutor(max_workers=10)
        for item in data:

            pid = item[0]

            def fast(region_id):

                db = pool.work_queue.get()
                info = self.get_city_traffic(citycode=region_id, db=db)  # 获取交通数据
                pool.work_queue.put(db)
                if len(info) == 0:
                    print("%d没有数据" % (region_id))

                    return
                # 数据写入
                for item in info:
                    sql = "insert into  digitalsmart.citytraffic(pid, ddate, ttime, rate)" \
                          " values('%d', '%d', '%s', '%f');" % (
                              region_id, item.date, item.detailtime, item.index)
                    pool.sumbit(sql)

            thread_pool.submit(fast, pid)
        print("城市交通数据挖掘完毕")

    def manager_city_road_traffic(self):
        """
        获取每个城市实时前10名拥堵道路数据-----10分钟执行一遍
        :return:
        """
        pool = ConnectPool(max_workers=10)

        up_date = int(datetime.datetime.now().timestamp())  # 记录最新的更新时间

        sql = "select pid from digitalsmart.citymanager"

        data = pool.select(sql)  # pid集合
        for item in data:  # 这里最好不要并发进行，因为每个pid任务下都有10个子线程，在这里开并发 的话容易被封杀

            pid = item[0]

            def fast(region_id):

                resultObjs = self.road_manager(region_id)  # 获取道路数据

                for obj in resultObjs:
                    region_id = obj.region_id
                    roadname = obj.roadname
                    speed = obj.speed
                    direction = obj.direction
                    bounds = obj.bounds
                    indexSet = obj.data
                    rate = obj.rate
                    roadid = obj.num  # 用排名表示道路id
                    sql = "insert into digitalsmart.roadtraffic(pid, roadname, up_date, speed, direction, bound, data," \
                          "roadid,rate) VALUE" \
                          "(%d,'%s',%d,%f,'%s','%s','%s',%d,%f) " % (
                              region_id, roadname, up_date, speed, direction, bounds,
                              indexSet, roadid, rate)

                    pool.sumbit(sql)
                    sql = "update  digitalsmart.roadmanager set up_date={0}  where pid={1} and roadid={2}" \
                        .format(up_date, region_id, roadid)

                    pool.sumbit(sql)  # 更新最近更新时间

            fast(pid)
        print("城市道路交通数据挖掘完毕")

    def manager_city_year_traffic(self):
        pool = ConnectPool(max_workers=10)
        sql = "select yearpid from digitalsmart.citymanager"
        thread_pool = ThreadPoolExecutor(max_workers=10)
        data = pool.select(sql)
        for item in data:

            yearpid = item[0]

            def fast(region_id):
                db = pool.work_queue.get()
                resultObj = self.yeartraffic(region_id, db)
                pool.work_queue.put(db)
                for item in resultObj:
                    region_id = item.region_id
                    date = item.date
                    index = item.index
                    sql_cmd = "insert into digitalsmart.yeartraffic(pid, tmp_date, rate) VALUE (%d,%d,%f)" % (
                        region_id, date, index)
                    pool.sumbit(sql_cmd)

            thread_pool.submit(fast, yearpid)

    def clear_road_data(self):
        """
        清除昨天的道路数据
        :return:
        """
        sql = "truncate table digitalsmart.roadtraffic"
        pool = ConnectPool(max_workers=1)
        pool.sumbit(sql)


