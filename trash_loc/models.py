from django.db import models
from common.models import TrashLoc

class TrashLoc(models.Model):
    t_lat = models.FloatField()
    t_lon = models.FloatField()
    t_road_addr = models.CharField(max_length=255)
    t_detailed_addr = models.CharField(max_length=255, null=True, blank=True)
    t_trash_type = models.CharField(max_length=100)
    t_loc = models.CharField(max_length=255)
    t_dept = models.CharField(max_length=100)
    t_contact = models.CharField(max_length=100)
    t_district_id = models.IntegerField()
 
