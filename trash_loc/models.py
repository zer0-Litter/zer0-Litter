from django.db import models

class TrashLoc(models.Model):
    t_district_id = models.CharField(max_length=100, primary_key=True)
    t_district = models.CharField(max_length=255, null=True, blank=True)
    t_road_addr = models.CharField(max_length=255, null=True, blank=True)
    t_street_addr = models.CharField(max_length=255, null=True, blank=True)
    t_detailed_addr = models.CharField(max_length=255, null=True, blank=True)
    t_lat = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    t_lon = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    t_loc = models.CharField(max_length=50, null=True, blank=True)
    t_shape = models.CharField(max_length=50, null=True, blank=True)
    t_trash_type = models.CharField(max_length=50, null=True, blank=True)
    t_dept = models.CharField(max_length=50, null=True, blank=True)
    t_contact = models.CharField(max_length=50, null=True, blank=True)
    t_date = models.DateField(null=True, blank=True)
    t_update_year = models.IntegerField(null=True, blank=True)
    t_addr = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'trash_loc'
