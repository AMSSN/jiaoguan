import cv2
import numpy as np
import re
from pathlib import Path


class OrderedSetList:
    """
    OrderedSetList 类结合了 list 和 set 的特性，旨在提供一个有序且唯一的元素集合。
    它维护元素的插入顺序，同时确保集合中的所有元素都是唯一的。
    """

    def __init__(self):
        """
        初始化 OrderedSetList 对象。
        self._list 用于维护元素的插入顺序。
        self._set 用于快速检查元素是否存在。
        """
        self._list = []
        self._set = set()

    def append(self, item):
        """
        如果 item 不在集合中，则将其添加到集合和列表中。
        这样可以确保所有元素都是唯一的，并且维持插入顺序。
        """
        if item not in self._set:
            self._list.append(item)
            self._set.add(item)

    def extend(self, items):
        """
        将多个元素添加到集合中。
        通过调用 append 方法，自动去重并保持顺序。
        """
        for item in items:
            self.append(item)

    def __contains__(self, item):
        """
        检查集合中是否存在指定的元素。
        通过 self._set 快速判断元素是否存在，提高查询效率。
        """
        return item in self._set

    def __len__(self):
        """
        返回集合中元素的数量。
        由于 self._list 维护了元素顺序，所以通过它来确定元素数量。
        """
        return len(self._list)

    def __getitem__(self, index):
        """
        支持通过索引访问集合中的元素。
        该方法使得 OrderedSetList 类的对象可以像列表一样被索引。
        """
        return self._list[index]

    def __iter__(self):
        """
        返回集合的迭代器。
        该方法使得 OrderedSetList 类的对象可以被迭代。
        """
        return iter(self._list)

    def __repr__(self):
        """
        返回集合的字符串表示。
        该方法主要用于调试和日志记录，提供对象的详细信息。
        """
        return f"{self.__class__.__name__}({self._list})"

    def remove(self, item):
        """
        如果元素存在于集合中，则从集合和列表中移除该元素。
        这样做可以确保元素的唯一性和有序性得到维护。
        """
        if item in self._set:
            self._list.remove(item)
            self._set.remove(item)

    def discard(self, item):
        """
        如果元素存在于集合中，则移除它，如果不存在则什么也不做。
        与 remove 方法不同的是，discard 在元素不存在时不抛出异常。
        """
        if item in self._set:
            self._list.remove(item)
            self._set.discard(item)

    def to_list(self):
        """
        将 OrderedSetList 转换为普通列表。
        该方法提供了一种方式来获取集合的副本，作为常规列表使用。
        """
        return self._list.copy()


def check_path(path, create=True, overwrite=False):
    """
    判断路径是否存在，并根据参数决定是否创建或重命名。

    参数：
    - path (Path/str): 路径
    - create (bool): 是否允许创建不存在的路径
    - overwrite (bool): 是否在路径存在时，基于原名追加 _1/_2/... 并创建

    返回：
    - bool: 按规则判断结果
    """
    p = Path(path)

    if p.exists():
        # 路径存在：始终返回 True（不管 create）
        if overwrite:
            parent = p.parent
            base_name = p.name
            # 构造正则：匹配以 base_name 开头 + 可选数字结尾 的文件夹
            pattern = re.compile(rf'^{re.escape(base_name)}(\d*)$')
            max_num = 0
            for item in parent.iterdir():
                if not item.is_dir():
                    continue
                match = pattern.match(item.name)
                if match:
                    num_str = match.group(1)
                    num = int(num_str) if num_str else 0  # 若无数字，默认视为 0（对应原名）
                    max_num = max(max_num, num)
            new_name = f"{base_name}{max_num + 1}"
            new_p = p.parent / new_name
            try:
                new_p.mkdir(parents=True)
                return new_p
            except Exception:
                return ""  # 创建失败也返回 False
        return p

    else:
        # 路径不存在：看 create
        if not create:
            return ""
        # 尝试创建
        try:
            p.mkdir(parents=True)
            return p
        except Exception:
            return ""


def imread_cn(path):
    """支持中文路径的 imread"""
    data = np.fromfile(path, dtype=np.uint8)  # 通过二进制读取数据，类型为无符号8位整数uint8
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img


def imwrite_cn(path, img):
    """支持中文路径的 imwrite"""
    ext = '.' + path.split('.')[-1]  # 获取扩展名
    _, data = cv2.imencode(ext, img)
    data.tofile(path)  # tofile 支持 Unicode 路径！
