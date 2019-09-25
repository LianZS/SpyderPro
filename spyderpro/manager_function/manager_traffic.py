import datetime
import json
from spyderpro.pool.threadpool import ThreadPool
from spyderpro.pool.mysql_connect import ConnectPool
from spyderpro.pool.redis_connect import RedisConnectPool
from spyderpro.function.traffic_function.traffic import Traffic


class ManagerTraffic(Traffic):
    """
    缓存数据：
        日常交通拥堵延迟指数：key= "traffic:{0}".format(region_id),mapping ={"HH:MM:SS":rate,....}
        道路交通数据：key ="road:{pid}:{road_id}".format(pid=region_id, road_id=roadid)
                        value =str( {
                            "pid": pid, "roadname": roadname, "up_date": up_date, "speed": speed,
                            "direction": direction, "bounds": bound, "data": data,
                            "roadpid": roadid, "rate": rate
                        })
        季度交通数据：key = "yeartraffic:{pid}".format(pid=region_id) ,value={'yyyymmdd':rate,....}

    """

    def __init__(self):
        self._redis_worker = RedisConnectPool(10)

    def __del__(self):
        del self._redis_worker

    def manager_city_traffic(self):
        """
        获取城市实时交通拥堵情况并写入数据库,半小时执行一次
        :return:
        """
        pool = ConnectPool(max_workers=10)
        sql = "select pid, name from digitalsmart.citymanager"
        data = pool.select(sql)
        # 千万不要开系统自带的线程池，占用的内存过大，而且每次线程退出后内存都没有释放，而是一直累加。使用自定义线程池，
        thread_pool = ThreadPool(max_workers=10)
        time_interval = datetime.timedelta(minutes=30)  # 缓存时间
        for item in data:

            pid = item[0]
            city = item[1]

            def fast(region_id, cityname):

                db = pool.work_queue.get()
                # 完整数据，过滤后的数据

                filter_info = self.get_city_traffic(citycode=region_id, db=db)  # 获取交通数据
                pool.work_queue.put(db)

                if filter_info is None:
                    print("pid:%d -- city:%s 没有数据" % (region_id, cityname))

                    return

                mapping = dict()  # 存放缓存数据

                # 数据写入
                for it in filter_info:
                    sql_cmd = "insert into  digitalsmart.citytraffic(pid, ddate, ttime, rate)" \
                              " values('%d', '%d', '%s', '%f');" % (
                                  region_id, it.date, it.detailtime, it.index)
                    mapping[it.detailtime] = it.index
                    pool.sumbit(sql_cmd)
                # 缓存数据
                redis_key = "traffic:{0}".format(region_id)

                self._redis_worker.hash_value_append(name=redis_key, mapping=mapping)
                self._redis_worker.expire(name=redis_key, time_interval=time_interval)

            thread_pool.submit(fast, pid, city)
        thread_pool.run()
        thread_pool.close()
        pool.close()
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
        time_interval = datetime.timedelta(minutes=30)  # 缓存时间

        for item in data:  # 这里最好不要并发进行，因为每个pid任务下都有10个子线程，在这里开并发 的话容易被封杀

            pid = item[0]

            def fast(region_id):
                result_objs = self.road_manager(region_id)  # 获取道路数据
                if result_objs is None:
                    return
                for obj in result_objs:
                    region_id = obj.region_id  # 标识
                    roadname = obj.roadname  # 路名
                    speed = obj.speed  # 速度
                    direction = obj.direction  # 方向
                    bounds = obj.bounds  # 经纬度数据集
                    road_traffic_rate_list = obj.road_index_data_list  # 拥堵指数集合
                    road_traffic_time_list = obj.time_data_list
                    num = obj.num
                    data_pack = json.dumps({"num": num, "time": road_traffic_time_list, "data": road_traffic_rate_list})
                    rate = obj.rate  # 当前拥堵指数
                    roadid = obj.num  # 用排名表示道路id
                    sql_insert = "insert into digitalsmart.roadtraffic(pid, roadname, up_date, speed, direction, " \
                                 "bound, data,roadid,rate) VALUE (%d,'%s',%d,%f,'%s','%s','%s',%d,%f) " % (
                                     region_id, roadname, up_date, speed, direction, bounds,
                                     data_pack, roadid, rate)
                    pool.sumbit(sql_insert)
                    sql_cmd = "update  digitalsmart.roadmanager set up_date={0}  where pid={1} and roadid={2}" \
                        .format(up_date, region_id, roadid)

                    pool.sumbit(sql_cmd)  # 更新最近更新时间
                    # 缓存数据
                    # if data is None or bounds is None:  # 道路拥堵指数数据包请求失败情况下
                    #     continue
                    redis_key = "road:{pid}:{road_id}".format(pid=region_id, road_id=roadid)
                    mapping = {
                        "pid": pid, "roadname": roadname, "up_date": up_date, "speed": speed,
                        "direction": direction, "bounds": bounds, "data": data_pack,
                        "roadpid": roadid, "rate": rate
                    }
                    self._redis_worker.set(redis_key, str(mapping))
                    self._redis_worker.expire(name=redis_key, time_interval=time_interval)

            fast(pid)

        pool.close()

        print("城市道路交通数据挖掘完毕")

    def manager_city_year_traffic(self):
        pool = ConnectPool(max_workers=10)
        sql = "select pid from digitalsmart.citymanager"

        thread_pool = ThreadPool(max_workers=10)
        data = pool.select(sql)
        for item in data:
            yearpid = item[0]

            def fast(region_id):

                db = pool.work_queue.get()
                result_objs = self.yeartraffic(region_id, db)

                pool.work_queue.put(db)
                if len(result_objs) == 0 or result_objs is None:  # 此次请求没有数据
                    return
                mapping = dict()

                for it in result_objs:
                    region_id = it.region_id
                    date = it.date
                    index = it.index
                    sql_cmd = "insert into digitalsmart.yeartraffic(pid, tmp_date, rate) VALUE (%d,%d,%f)" % (
                        region_id, date, index)
                    pool.sumbit(sql_cmd)
                    mapping[date] = index

                redis_key = "yeartraffic:{pid}".format(pid=region_id)
                self._redis_worker.hash_value_append(redis_key, mapping)

            thread_pool.submit(fast, yearpid)
        thread_pool.run()
        thread_pool.close()
        pool.close()


if __name__ == "__main__":
    from multiprocessing import Process

    m = ManagerTraffic()
    Process(target=m.manager_city_road_traffic).start()
    Process(target=m.manager_city_traffic).start()
    Process(target=m.manager_city_year_traffic).start()