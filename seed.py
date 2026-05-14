import pandas as pd
import numpy as np

from database import SessionLocal, engine
from models import Base
from models import *

file_path = "Hospital Management System.xlsx"
db = SessionLocal()


def clean(v):
    if pd.isna(v):
        return None

    if isinstance(v, (np.integer,)):
        return int(v)

    if isinstance(v, (np.floating,)):
        return float(v)

    return v


def read_sheet(name):
    df = pd.read_excel(file_path, sheet_name=name)
    df = df.astype(object)
    return df


def seed_generic(sheet, model):
    print(f"Seeding {sheet}")

    df = read_sheet(sheet)

    for _, r in df.iterrows():
        data = {k: clean(v) for k, v in r.to_dict().items()}
        db.add(model(**data))

    db.commit()

    print(f"{sheet} inserted: {len(df)}")
def seed_roles():
    roles = [
        Role(id=1, name="Admin"),
        Role(id=2, name="Doctor"),
        Role(id=3, name="Nurse"),
        Role(id=4, name="Patient"),
        Role(id=5, name="Helper"),
        Role(id=6, name="Receptionist"),
    ]

    for r in roles:
        db.add(r)

    db.commit()
    print("Roles inserted:", len(roles))

def run_all():
    seed_roles()

    seed_generic("Department", Department)
    seed_generic("Users", User)

    seed_generic("Doctor", Doctor)
    seed_generic("Nurse", Nurse)
    seed_generic("Helpers", Helper)
    seed_generic("Patients", Patient)

    seed_generic("Ward", Ward)
    seed_generic("Room", Room)
    seed_generic("Bed", Bed)

    seed_generic("Appointment", Appointment)
    seed_generic("MedicalRecord", MedicalRecord)
    seed_generic("SurgeryRecord", SurgeryRecord)
    seed_generic("StaffShift", StaffShift)
    seed_generic("BedRecords", BedRecord)
    seed_generic("RoomRecords", RoomRecord)


if __name__ == "__main__":

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    run_all()