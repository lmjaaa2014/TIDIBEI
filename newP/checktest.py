import operator
from datetime import datetime
from filecmp import cmp
import pandas as pd
import numpy as np

from datetime import date, timedelta
dt = date.today() - timedelta(5)
print('Current Date :',date.today())
print('5 days before Current Date :',dt)
