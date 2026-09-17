# -*- coding: utf-8 -*-
"""اختبارات العملاء: البحث وترتيب الأكثر تعاملاً وإحصاءات كل عميل."""

import datetime

import pytest

from app.repositories import customers_repo, vehicles_repo
from app.services import rental_service


def _customer(conn, name, national_id, phone="0910000000"):
    return customers_repo.create(
        {
            "full_name": name,
            "phone": phone,
            "national_id": national_id,
            "license_number": "LC-" + national_id,
        },
        conn=conn,
    )


def _vehicle(conn, plate):
    return vehicles_repo.create(
        {
            "brand": "تويوتا", "model": "ياريس", "year": 2023, "plate_number": plate,
            "color": "أبيض", "daily_rate": 10000, "weekly_rate": 0,
            "currency_code": "LYD",
        },
        conn=conn,
    )


def _rent(conn, customer_id, vehicle_id, day_offset, days=2):
    today = datetime.date.today()
    start = today + datetime.timedelta(days=day_offset)
    return rental_service.open_contract(
        customer_id, vehicle_id,
        start.isoformat(), (start + datetime.timedelta(days=days)).isoformat(),
        conn=conn,
    )


def test_search_reports_contract_counts(conn, admin):
    customer = _customer(conn, "خالد الورفلي", "111111")
    vehicle = _vehicle(conn, "1-11111")
    _rent(conn, customer, vehicle, 0)
    _rent(conn, customer, vehicle, 10)

    row = customers_repo.search("خالد", conn=conn)[0]
    assert row["contracts_count"] == 2
    assert row["last_contract_date"]
    assert row["total_spent"] == 2 * 2 * 10000       # عقدان × يومان × 100.00


def test_customer_without_contracts_counts_zero(conn, admin):
    _customer(conn, "عميل جديد", "222222")
    row = customers_repo.search("عميل جديد", conn=conn)[0]
    assert row["contracts_count"] == 0
    assert row["total_spent"] == 0


def test_frequent_ordering_puts_repeat_customers_first(conn, admin):
    """الترتيب بالأكثر تعاملاً: من يتردّد على المكتب كثيراً يظهر أولاً."""
    rare = _customer(conn, "أحمد النادر", "333333")
    loyal = _customer(conn, "بشير المتكرّر", "444444")

    first_vehicle = _vehicle(conn, "2-22222")
    second_vehicle = _vehicle(conn, "3-33333")

    _rent(conn, rare, first_vehicle, 0)
    for offset in (0, 10, 20):
        _rent(conn, loyal, second_vehicle, offset)

    # الترتيب الأبجدي يضع «أحمد» أولاً
    by_name = customers_repo.search(conn=conn)
    assert by_name[0]["full_name"] == "أحمد النادر"

    # وترتيب الأكثر تعاملاً يضع «بشير» أولاً
    by_frequency = customers_repo.search(order_by="frequent", conn=conn)
    assert by_frequency[0]["full_name"] == "بشير المتكرّر"
    assert by_frequency[0]["contracts_count"] == 3


def test_frequent_helper_excludes_one_time_customers(conn, admin):
    once = _customer(conn, "زائر واحد", "555555")
    twice = _customer(conn, "زبون معتاد", "666666")

    _rent(conn, once, _vehicle(conn, "4-44444"), 0)
    repeat_vehicle = _vehicle(conn, "5-55555")
    _rent(conn, twice, repeat_vehicle, 0)
    _rent(conn, twice, repeat_vehicle, 10)

    names = [row["full_name"] for row in customers_repo.frequent(conn=conn)]
    assert "زبون معتاد" in names
    assert "زائر واحد" not in names


def test_cancelled_contracts_do_not_count(conn, admin):
    """العقد الملغى لا يجعل العميل متكرّراً ولا يُحتسب في إنفاقه."""
    customer = _customer(conn, "عميل ألغى", "777777")
    vehicle = _vehicle(conn, "6-66666")

    contract_id, _ = _rent(conn, customer, vehicle, 0)
    _rent(conn, customer, vehicle, 10)
    rental_service.cancel_contract(contract_id, reason="اختبار", conn=conn)

    row = customers_repo.search("عميل ألغى", conn=conn)[0]
    assert row["contracts_count"] == 1


# ---------------------------------------------------------------------------
# العميل السريع وبياناته الناقصة
# ---------------------------------------------------------------------------
def test_customer_can_be_created_with_a_name_only(conn, admin):
    """المكتب يستقبل زبوناً واقفاً أمامه فيكتب اسمه ويمضي."""
    customer_id = customers_repo.create({"full_name": "زبون عابر"}, conn=conn)

    row = customers_repo.get(customer_id, conn=conn)
    assert row["full_name"] == "زبون عابر"
    assert row["phone"] is None
    assert row["national_id"] is None


def test_a_name_is_still_required(conn, admin):
    with pytest.raises(ValueError) as error:
        customers_repo.create({"phone": "0912345678"}, conn=conn)
    assert "اسم" in str(error.value)


def test_incomplete_names_exactly_what_is_missing(conn, admin):
    partial = customers_repo.get(
        customers_repo.create({"full_name": "ناقص", "phone": "0911"}, conn=conn),
        conn=conn,
    )
    full = customers_repo.get(
        customers_repo.create(
            {"full_name": "مكتمل", "phone": "0912", "national_id": "N-1",
             "license_number": "LC-1"},
            conn=conn,
        ),
        conn=conn,
    )

    assert customers_repo.is_incomplete(partial)
    assert customers_repo.missing_fields(partial) == [
        "رقم الجواز أو الرقم الوطني", "رقم رخصة القيادة",
    ]

    assert not customers_repo.is_incomplete(full)
    assert customers_repo.missing_fields(full) == []


def test_two_incomplete_customers_do_not_collide(conn, admin):
    """رقمان وطنيان فارغان ليسا تكراراً — وإلّا تعذّر تسجيل أكثر من زبون عابر."""
    customers_repo.create({"full_name": "أول"}, conn=conn)
    customers_repo.create({"full_name": "ثانٍ"}, conn=conn)

    names = {row["full_name"] for row in customers_repo.search(conn=conn)}
    assert {"أول", "ثانٍ"} <= names


def test_duplicate_national_id_is_still_refused(conn, admin):
    """تخفيف الإلزام لا يعني تخفيف التفرّد: ملفّان لعميل واحد خطأ محاسبي."""
    customers_repo.create(
        {"full_name": "أوّل", "national_id": "SAME-1"}, conn=conn
    )
    with pytest.raises(ValueError):
        customers_repo.create(
            {"full_name": "ثانٍ", "national_id": "SAME-1"}, conn=conn
        )


def test_incomplete_customer_can_still_rent(conn, admin, sample_vehicle):
    """العميل الناقص يعمل في المنظومة كاملاً — النقص يُعلَّم ولا يُعطّل."""
    import datetime

    from app.services import rental_service

    customer_id = customers_repo.create({"full_name": "زبون عابر"}, conn=conn)
    today = datetime.date.today()

    contract_id, number = rental_service.open_contract(
        customer_id, sample_vehicle, today.isoformat(),
        (today + datetime.timedelta(days=2)).isoformat(), conn=conn,
    )
    assert contract_id and number


def test_incomplete_customer_does_not_break_search_rows(conn, admin):
    customers_repo.create({"full_name": "زبون عابر"}, conn=conn)
    rows = customers_repo.search(conn=conn)
    assert any(customers_repo.is_incomplete(row) for row in rows)


# ---------------------------------------------------------------------------
# تطبيع المعرّفات الفريدة
# ---------------------------------------------------------------------------
def test_whitespace_around_national_id_does_not_create_a_duplicate(conn, admin):
    """‹١١٩٨٧٦› و‹ ١١٩٨٧٦ › عميل واحد لا عميلان.

    الفحص كان يقصّ المسافات والحفظ يُبقيها، فيمرّ الرقم نفسه مرّتين ويظهر
    للمكتب عميلان لشخص واحد — وهو أسوأ من الرفض، لأن الخطأ لا يُكتشف إلّا
    بعد أن تتفرّق عقوده بين ملفّين.
    """
    customers_repo.create(
        {"full_name": "سالم التلاتي", "national_id": "  119876543210  "}, conn=conn
    )

    with pytest.raises(ValueError) as error:
        customers_repo.create(
            {"full_name": "سالم التلاتي", "national_id": "119876543210"}, conn=conn
        )
    assert "نفس رقم الجواز" in str(error.value)


def test_customer_identifiers_are_stored_trimmed(conn, admin):
    customer_id = customers_repo.create(
        {"full_name": "  فرج المبروك  ", "national_id": " 777888 ",
         "license_number": " LC-77 ", "phone": " 0913333333 "},
        conn=conn,
    )
    row = customers_repo.get(customer_id, conn=conn)
    assert row["full_name"] == "فرج المبروك"
    assert row["national_id"] == "777888"
    assert row["license_number"] == "LC-77"
    assert row["phone"] == "0913333333"


def test_whitespace_around_plate_number_does_not_create_a_duplicate(conn, admin):
    from app.repositories import vehicles_repo

    data = {"brand": "كيا", "model": "ريو", "year": 2021, "plate_number": "7-54321",
            "color": "أزرق", "daily_rate": 12000, "weekly_rate": 0,
            "currency_code": "LYD"}
    vehicles_repo.create(dict(data, plate_number="  7-54321  "), conn=conn)

    with pytest.raises(ValueError) as error:
        vehicles_repo.create(dict(data), conn=conn)
    assert "نفس رقم اللوحة" in str(error.value)


def test_plate_number_is_stored_trimmed(conn, admin):
    from app.repositories import vehicles_repo

    vehicle_id = vehicles_repo.create(
        {"brand": "هوندا", "model": "سيفيك", "year": 2020, "plate_number": " 8-1234 ",
         "color": "أسود", "daily_rate": 11000, "weekly_rate": 0, "currency_code": "LYD"},
        conn=conn,
    )
    assert vehicles_repo.get(vehicle_id, conn=conn)["plate_number"] == "8-1234"
