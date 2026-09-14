# -*- coding: utf-8 -*-
"""مساعدات بناء عبارات SQL للمستودعات.

سبب وجودها: إدراج كل الأعمدة دائماً — حتى غير المُدخَلة — يُرسل ``NULL`` إلى
أعمدة لها قيمة افتراضية مثل ``is_blacklisted`` و ``weekly_rate``، فيفشل قيد
``NOT NULL``. الحل أن نُدرج **ما أُدخل فعلاً** فقط، وتتكفّل قاعدة البيانات
بالبقيّة.
"""


def insert(table, data, fields, conn_execute):
    """يُدرج صفّاً بالأعمدة الموجودة في ``data`` فقط، ويُرجع معرّف الصفّ الجديد."""
    present = [field for field in fields if data.get(field) is not None]
    if not present:
        raise ValueError("لا توجد بيانات للحفظ.")

    sql = "INSERT INTO %s (%s) VALUES (%s)" % (
        table, ", ".join(present), ", ".join("?" * len(present))
    )
    cursor = conn_execute(sql, [data[field] for field in present])
    return cursor.lastrowid


def update(table, row_id, data, fields, conn_execute):
    """يحدّث الأعمدة المذكورة في ``fields`` بقيم ``data``.

    القيم الغائبة تُكتب ``NULL`` عمداً هنا: التعديل يعكس النموذج كما عرضه
    المستخدم، فإفراغ حقل اختياري يجب أن يُفرغه فعلاً.
    """
    assignments = ", ".join("%s = ?" % field for field in fields)
    values = [data.get(field) for field in fields] + [row_id]
    conn_execute("UPDATE %s SET %s WHERE id = ?" % (table, assignments), values)
    return True
