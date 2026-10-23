from datetime import date
from db import Database
from models import CheckIn, Impulse

db = Database(":memory:")
db.init_schema()
uid = db.get_or_create_user(12345)

db.add_checkin(uid, CheckIn(date.today(), mood=6, energy=4, stress=7,
                            episode=True, episode_minutes=40))
iid = db.add_impulse(uid, Impulse(date.today(), "boredom", 3))
db.set_technique(iid, "pause_shake")
db.set_helped(iid, True)

print(db.get_checkins(uid, 7))
print(db.get_impulses(uid, 7))