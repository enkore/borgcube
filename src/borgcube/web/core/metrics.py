from persistent.list import PersistentList

import transaction

from borgcube.core.models import Evolvable


class WebData(Evolvable):
    def __init__(self):
        self.metrics = PersistentList()

        from .builtin_metrics import ArchiveCount, TotalData, BackupsToday
        self.metrics.append(ArchiveCount())
        self.metrics.append(TotalData())
        self.metrics.append(BackupsToday())
        transaction.get().note('web: added default metrics')
        transaction.commit()


class Metric:
    name = None
    label = None

    def formatted_value(self):
        pass
