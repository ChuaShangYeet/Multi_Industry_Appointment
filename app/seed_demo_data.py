"""
One-off script that fills the database with realistic demo data covering
every business category, resource type, and appointment lifecycle state -
so you can exercise the whole API surface via /docs immediately instead of
manually clicking through register -> approve -> add service -> book for
every scenario by hand.

Run with:

    python -m app.seed_demo_data

Safe to re-run: it checks for its own marker business first and does
nothing if the demo data already exists. To start over, delete dev.db and
re-run `alembic upgrade head` first.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
from zoneinfo import ZoneInfo

import app.models  # noqa: F401 - ensure every table is registered on Base.metadata
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.enums import (
    AccountStatus,
    AdminRoleLevel,
    AppointmentStatus,
    AppointmentType,
    BusinessApprovalStatus,
    BusinessCategory,
    SpaceInventoryType,
    TablePreference,
)
from app.models.admin import AdminUser
from app.models.appointment import Appointment
from app.models.business import Business
from app.models.details import CarServiceDetails, GeneralServiceDetails, HotelDetails, HotelRoomItem, RestaurantDetails
from app.models.resource import Service, SpaceInventory, Staff
from app.models.user import User
from app.security import hash_password

DEMO_PASSWORD = "Password123!"
MARKER_BUSINESS_EMAIL = "salon.demo@example.com"
DEMO_TZ = ZoneInfo("Asia/Kuala_Lumpur")  # matches every seeded business's own Business.timezone


def _future(days: int, hour: int = 10) -> datetime:
    # Built in the business's own timezone (not UTC) so a seeded "10:00 AM"
    # appointment actually displays as 10:00 AM Malaysia time in the
    # frontend, rather than 10:00 AM UTC (6:00 PM locally) - it's then
    # normalized to UTC for storage the same way a real booking would be
    # (see app.db_types.UTCDateTime).
    dt = datetime.now(DEMO_TZ) + timedelta(days=days)
    return dt.replace(hour=hour, minute=0, second=0, microsecond=0)


def _past(days: int, hour: int = 10) -> datetime:
    return _future(-days, hour)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Business).filter(Business.email == MARKER_BUSINESS_EMAIL).first():
            print("Demo data already present (found the marker business) - nothing to do.")
            print("Delete dev.db and run `alembic upgrade head` first if you want a clean reseed.")
            return

        # --- Admin -----------------------------------------------------
        admin = db.query(AdminUser).filter(AdminUser.email == settings.FIRST_ADMIN_EMAIL).first()
        if admin is None:
            admin = AdminUser(
                email=settings.FIRST_ADMIN_EMAIL,
                password_hash=hash_password(settings.FIRST_ADMIN_PASSWORD),
                role_level=AdminRoleLevel.SUPER_ADMIN,
                first_name="Super",
                last_name="Admin",
            )
            db.add(admin)
            db.flush()

        # --- Customers ---------------------------------------------------
        # Aisha is deliberately given a different display timezone than her
        # +60 (Malaysia) phone number's country - demonstrates a customer
        # traveling abroad still sees her appointment times converted
        # correctly to wherever she actually is, while the underlying
        # booking stays anchored to the business's own timezone.
        customers = {}
        for email, first, last, phone, tz in [
            ("jane.demo@example.com", "Jane", "Doe", "+60123456789", "Asia/Kuala_Lumpur"),
            ("john.demo@example.com", "John", "Smith", "+60129876543", "Asia/Kuala_Lumpur"),
            ("aisha.demo@example.com", "Aisha", "Bee", "+60125551234", "America/New_York"),
            # A non-Malaysian customer, deliberately, so the currency-conversion
            # display (Business.currency -> a customer's own currency, inferred
            # from their phone number's country - see frontend/src/countries.ts)
            # has someone to actually show a converted price to; every other
            # demo customer's +60 number matches every demo business's MYR, so
            # there'd otherwise be nothing to convert.
            ("wei.demo@example.com", "Wei", "Chen", "+8613800138000", "Asia/Shanghai"),
        ]:
            user = User(
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                first_name=first,
                last_name=last,
                phone_number=phone,
                account_status=AccountStatus.ACTIVE,
                timezone=tz,
            )
            db.add(user)
            db.flush()
            customers[email] = user

        # --- Businesses, one per category, pre-Approved -------------------
        # All demo businesses genuinely operate out of Malaysia, so they all
        # share one timezone - this is what their operating_hours and every
        # appointment booked with them is anchored to.
        BUSINESS_TIMEZONE = "Asia/Kuala_Lumpur"

        WEEKDAY_9_TO_6 = {"open": "09:00", "close": "18:00"}
        DEFAULT_OPERATING_HOURS = {
            "monday": WEEKDAY_9_TO_6,
            "tuesday": WEEKDAY_9_TO_6,
            "wednesday": WEEKDAY_9_TO_6,
            "thursday": WEEKDAY_9_TO_6,
            "friday": WEEKDAY_9_TO_6,
            "saturday": {"open": "10:00", "close": "16:00"},
            "sunday": None,
        }

        # Sequential local numbers under Malaysia's own country code, so a customer
        # looking at the Business Details page has a real-looking number to call.
        _phone_suffixes = count(23456789)

        def make_business(email, name, category, city, rating, rating_count, hours=None):
            biz = Business(
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                business_name=name,
                category=category,
                approval_status=BusinessApprovalStatus.APPROVED,
                description=f"Demo {category.value.lower()} business for API testing.",
                address=f"123 Demo Street, {city}",
                city=city,
                cover_image_url=f"https://picsum.photos/seed/{email.split('@')[0]}/640/400",
                phone_number=f"+603{next(_phone_suffixes)}",
                average_rating=rating,
                rating_count=rating_count,
                operating_hours=hours or DEFAULT_OPERATING_HOURS,
                timezone=BUSINESS_TIMEZONE,
                currency="MYR",
            )
            db.add(biz)
            db.flush()
            return biz

        salon = make_business(MARKER_BUSINESS_EMAIL, "Sarah's Hair Salon", BusinessCategory.SALON, "Kuala Lumpur", 4.7, 132)
        spa = make_business("spa.demo@example.com", "Serenity Spa", BusinessCategory.SPA, "Petaling Jaya", 4.9, 87)
        car = make_business("auto.demo@example.com", "QuickFix Auto Service", BusinessCategory.CAR_SERVICE, "Subang Jaya", 4.3, 54)
        pro = make_business("tax.demo@example.com", "Ahmad & Co Tax Consultants", BusinessCategory.PROFESSIONAL, "Kuala Lumpur", 4.8, 21)
        restaurant = make_business("restaurant.demo@example.com", "The Golden Spoon", BusinessCategory.RESTAURANT, "Bangsar", 4.5, 210)
        hotel = make_business("hotel.demo@example.com", "Sunset Beach Hotel", BusinessCategory.HOTEL, "Penang", 4.6, 340)

        # Also leave one Pending business so you can try the admin-approval flow.
        make_business("newspa.demo@example.com", "New Wave Nails", BusinessCategory.SPA, "Cheras", 0.0, 0)
        db.query(Business).filter(Business.email == "newspa.demo@example.com").first().approval_status = (
            BusinessApprovalStatus.PENDING
        )

        # --- Staff (for staff-based categories) ---------------------------
        sarah_lee = Staff(business_id=salon.id, name="Sarah Lee", role_type="Senior Stylist")
        mike_tan = Staff(business_id=salon.id, name="Mike Tan", role_type="Stylist")
        lily_wong = Staff(business_id=spa.id, name="Lily Wong", role_type="Massage Therapist")
        ahmad_ismail = Staff(business_id=car.id, name="Ahmad Ismail", role_type="Mechanic")
        dr_ahmad = Staff(business_id=pro.id, name="Dr. Ahmad Rahman", role_type="Tax Consultant")
        db.add_all([sarah_lee, mike_tan, lily_wong, ahmad_ismail, dr_ahmad])
        db.flush()

        # --- Space inventory (for space-based categories) -----------------
        window_table = SpaceInventory(
            business_id=restaurant.id,
            inventory_type=SpaceInventoryType.RESTAURANT_TABLE,
            category_name="Window Table 4-Pax",
            total_quantity=4,
            capacity_per_unit=4,
        )
        indoor_table = SpaceInventory(
            business_id=restaurant.id,
            inventory_type=SpaceInventoryType.RESTAURANT_TABLE,
            category_name="Indoor Table 2-Pax",
            total_quantity=10,
            capacity_per_unit=2,
        )
        deluxe_room = SpaceInventory(
            business_id=hotel.id,
            inventory_type=SpaceInventoryType.HOTEL_ROOM,
            category_name="Deluxe Double Room",
            total_quantity=15,
            capacity_per_unit=2,
            price=150,
        )
        suite = SpaceInventory(
            business_id=hotel.id,
            inventory_type=SpaceInventoryType.HOTEL_ROOM,
            category_name="Suite",
            total_quantity=3,
            capacity_per_unit=4,
            price=350,
        )
        db.add_all([window_table, indoor_table, deluxe_room, suite])
        db.flush()

        # --- Services -------------------------------------------------------
        haircut = Service(business_id=salon.id, name="Haircut", duration_minutes=30, price=25)
        coloring = Service(business_id=salon.id, name="Hair Coloring", duration_minutes=90, price=80)
        massage = Service(business_id=spa.id, name="Swedish Massage", duration_minutes=60, price=60)
        oil_change = Service(business_id=car.id, name="Oil Change", duration_minutes=45, price=40)
        tax_consult = Service(business_id=pro.id, name="Tax Consultation", duration_minutes=60, price=100)
        table_booking = Service(business_id=restaurant.id, name="Standard Table Booking", duration_minutes=90)
        # No price here - a hotel's nightly rate is per room type (see
        # SpaceInventory.price above), not one flat rate every room shares.
        room_booking = Service(business_id=hotel.id, name="Room Booking", duration_minutes=1440)
        db.add_all([haircut, coloring, massage, oil_change, tax_consult, table_booking, room_booking])
        db.flush()

        jane, john, aisha = customers["jane.demo@example.com"], customers["john.demo@example.com"], customers["aisha.demo@example.com"]

        # --- Appointments across every status + industry -------------------
        def add_appointment(**kwargs):
            appt = Appointment(**kwargs)
            db.add(appt)
            db.flush()
            return appt

        # 1) Confirmed haircut, tomorrow (Salon / staff-based)
        a1 = add_appointment(
            user_id=jane.id, business_id=salon.id, service_id=haircut.id, staff_id=sarah_lee.id,
            appointment_type=AppointmentType.SALON, start_datetime=_future(1),
            end_datetime=_future(1) + timedelta(minutes=30), status=AppointmentStatus.CONFIRMED,
        )
        db.add(GeneralServiceDetails(appointment_id=a1.id, staff_requested_id=sarah_lee.id, service_specifics={"note": "Bob cut, shoulder length"}))

        # 2) Pending massage, in 2 days (Spa / staff-based, no specific staff requested)
        a2 = add_appointment(
            user_id=john.id, business_id=spa.id, service_id=massage.id, staff_id=None,
            appointment_type=AppointmentType.SPA, start_datetime=_future(2, 14),
            end_datetime=_future(2, 14) + timedelta(minutes=60), status=AppointmentStatus.PENDING,
        )
        db.add(GeneralServiceDetails(appointment_id=a2.id, service_specifics={"note": "Lower back tension"}))

        # 3) Cancelled oil change, in 3 days (Car Service)
        a3 = add_appointment(
            user_id=aisha.id, business_id=car.id, service_id=oil_change.id, staff_id=ahmad_ismail.id,
            appointment_type=AppointmentType.CAR, start_datetime=_future(3),
            end_datetime=_future(3) + timedelta(minutes=45), status=AppointmentStatus.CANCELLED,
            cancellation_reason="Customer rescheduled to next month",
        )
        db.add(CarServiceDetails(appointment_id=a3.id, car_brand="Toyota", car_model="Vios", plate_number="WXY1234", service_type="Oil Change"))

        # 4) Confirmed table booking, tomorrow evening (Restaurant / space-based)
        a4 = add_appointment(
            user_id=jane.id, business_id=restaurant.id, service_id=table_booking.id, space_inventory_id=window_table.id,
            appointment_type=AppointmentType.RESTAURANT, start_datetime=_future(1, 19),
            end_datetime=_future(1, 19) + timedelta(minutes=90), status=AppointmentStatus.CONFIRMED,
        )
        db.add(RestaurantDetails(appointment_id=a4.id, no_of_pax=4, table_preference=TablePreference.WINDOW, special_requests="Birthday celebration, window seat please"))

        # 5) Pending room booking, in 5 days, a 3-night stay (Hotel / space-based) -
        # demonstrates a real multi-night stay rather than one fixed-duration slot.
        a5 = add_appointment(
            user_id=john.id, business_id=hotel.id, service_id=room_booking.id, space_inventory_id=deluxe_room.id,
            appointment_type=AppointmentType.HOTEL, start_datetime=_future(5, 15),
            end_datetime=_future(8, 11), status=AppointmentStatus.PENDING,
        )
        db.add(HotelDetails(appointment_id=a5.id, room_type="Deluxe Double Room", no_of_rooms=1, no_of_guests=2, expected_check_in_time="15:00", expected_check_out_time="11:00"))
        db.add(HotelRoomItem(appointment_id=a5.id, space_inventory_id=deluxe_room.id, quantity=1))

        # 6) Completed tax consultation, 3 days ago (Professional / staff-based, specific staff requested)
        a6 = add_appointment(
            user_id=aisha.id, business_id=pro.id, service_id=tax_consult.id, staff_id=dr_ahmad.id,
            appointment_type=AppointmentType.PROFESSIONAL, start_datetime=_past(3),
            end_datetime=_past(3) + timedelta(minutes=60), status=AppointmentStatus.COMPLETED,
        )
        db.add(GeneralServiceDetails(appointment_id=a6.id, staff_requested_id=dr_ahmad.id, service_specifics={"topic": "Annual income tax filing"}))

        # 7) Confirmed massage further out, in 10 days (exercises the admin "active" +/-1 month window)
        a7 = add_appointment(
            user_id=jane.id, business_id=spa.id, service_id=massage.id, staff_id=lily_wong.id,
            appointment_type=AppointmentType.SPA, start_datetime=_future(10, 11),
            end_datetime=_future(10, 11) + timedelta(minutes=60), status=AppointmentStatus.CONFIRMED,
        )
        db.add(GeneralServiceDetails(appointment_id=a7.id, staff_requested_id=lily_wong.id, service_specifics={}))

        db.commit()

        print("Seed complete.\n")
        print(f"Admin      : {settings.FIRST_ADMIN_EMAIL} / {settings.FIRST_ADMIN_PASSWORD}")
        print(
            f"Customers  : jane.demo@example.com / john.demo@example.com / aisha.demo@example.com / "
            f"wei.demo@example.com (+86, sees prices converted from MYR to CNY)  (password: {DEMO_PASSWORD})"
        )
        print(f"Businesses : salon.demo@example.com, spa.demo@example.com, auto.demo@example.com, tax.demo@example.com,")
        print(f"             restaurant.demo@example.com, hotel.demo@example.com  (password: {DEMO_PASSWORD})")
        print(f"             + newspa.demo@example.com (still Pending - try approving it as admin)")
        print("\nAppointments seeded: 1 Confirmed, 1 Pending, 1 Cancelled, 1 Confirmed (restaurant),")
        print("                      1 Pending (hotel), 1 Completed, 1 Confirmed (further out) = 7 total,")
        print("                      spanning every category and every lifecycle status.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
