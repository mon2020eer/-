# -*- coding: utf-8 -*-
"""محرّر مواضع الحقول على نموذج عقد المكتب.

المكتب يرفع ورقة عقده، ثم يخبر المنظومة أين يُكتب كل شيء عليها: ينقر اسم الحقل
في القائمة، ثم ينقر موضعه على الصورة. لا صيغ ولا إحداثيات يكتبها بيده.

**الإحداثيات نسبية (0..1) لا بالبكسل** لأن الصفحة تُعرض هنا بمقاس الشاشة وتُطبع
بدقّة أعلى بكثير؛ النسبة وحدها تصمد لهذا الاختلاف.
"""

import pathlib

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
)

from ... import config
from ...services import pdf_template
from ..widgets.common import Card, primary_button, show_error, show_info

# نصف قطر علامة الموضع بالبكسل — كبيرة بما يكفي لتُنقر بالفأرة بلا تصويب دقيق
MARKER_RADIUS = 7


class PageCanvas(QLabel):
    """صفحة النموذج مع علامات المواضع: نقرٌ يضع، وسحبٌ يزيح."""

    placed = pyqtSignal(str, float, float)      # (مفتاح الحقل، x، y) نسبية
    picked = pyqtSignal(str)                    # نُقرت علامة حقل موجود

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        # الصورة تُرسم بإحداثيات أعلى-يسار دائماً، فلا يعكسها اتجاه التطبيق
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self._source = QImage()      # الصفحة بدقّتها الأصلية
        self._image = QImage()       # المعروضة بعد التحجيم لتناسب النافذة
        self._page = 0
        self._mapping = {}
        self._active_key = None
        self._dragging = None

    # ------------------------------------------------------------------
    def load_page(self, image, page):
        self._source = image
        self._page = page
        self._apply(image)

    def fit_to_height(self, height):
        """يحجّم الصفحة لتُرى كاملة في النافذة.

        صفحة A4 بدقّة مقروءة أطول من أي شاشة، والتعيين على جزء منها يجعل
        المكتب يمرّر صعوداً ونزولاً في كل حقل. والتحجيم آمن لأن المواضع
        تُخزَّن نسبةً لا بكسلات.
        """
        if self._source.isNull() or height <= 0:
            return
        scaled = self._source.scaledToHeight(
            int(height), Qt.TransformationMode.SmoothTransformation
        )
        self._apply(scaled)

    def _apply(self, image):
        self._image = image
        self.setPixmap(QPixmap.fromImage(image))
        self.setFixedSize(image.size())
        self.update()

    def set_mapping(self, mapping):
        self._mapping = mapping
        self.update()

    def set_active_field(self, key):
        self._active_key = key
        self.update()

    # ------------------------------------------------------------------
    def _spots_on_page(self):
        for key, spot in self._mapping.items():
            if int(spot.get("page", 0)) == self._page:
                yield key, spot

    def _to_pixels(self, spot):
        return QPoint(
            int(float(spot.get("x", 0.5)) * self.width()),
            int(float(spot.get("y", 0.5)) * self.height()),
        )

    def _hit(self, position):
        """أي علامة تحت المؤشّر؟ الأقرب تفوز عند التزاحم."""
        best, best_distance = None, MARKER_RADIUS * 2
        for key, spot in self._spots_on_page():
            point = self._to_pixels(spot)
            distance = (point - position).manhattanLength()
            if distance <= best_distance:
                best, best_distance = key, distance
        return best

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        position = event.position().toPoint()

        hit = self._hit(position)
        if hit is not None:
            self._dragging = hit
            self.picked.emit(hit)
            return

        if self._active_key:
            self._emit_position(self._active_key, position)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._emit_position(self._dragging, event.position().toPoint())

    def mouseReleaseEvent(self, event):
        self._dragging = None

    def _emit_position(self, key, position):
        if self.width() <= 0 or self.height() <= 0:
            return
        x = min(max(position.x() / self.width(), 0.0), 1.0)
        y = min(max(position.y() / self.height(), 0.0), 1.0)
        self.placed.emit(key, x, y)

    # ------------------------------------------------------------------
    def paintEvent(self, event):
        super().paintEvent(event)
        if self._image.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)

        for key, spot in self._spots_on_page():
            point = self._to_pixels(spot)
            active = key == self._active_key

            fill = QColor("#2f6fed") if active else QColor("#16a34a")
            painter.setBrush(fill)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawEllipse(point, MARKER_RADIUS, MARKER_RADIUS)

            # خطّ الأساس: يُري المكتب على أي سطر سيقع النصّ فعلاً
            painter.setPen(QPen(fill, 1, Qt.PenStyle.DashLine))
            painter.drawLine(0, point.y(), self.width(), point.y())

            label = pdf_template.FIELD_LABELS.get(key, key)
            metrics = painter.fontMetrics()
            width = metrics.horizontalAdvance(label) + 10
            box = QRect(point.x() - width - MARKER_RADIUS - 4,
                        point.y() - metrics.height() - MARKER_RADIUS,
                        width, metrics.height() + 2)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 225))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QColor("#111111"))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), label)

        painter.end()


class TemplateEditor(QDialog):
    """نافذة تعيين مواضع الحقول على نموذج المكتب."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تحديد مواضع الحقول على نموذج العقد")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(1000, 640)

        self._mapping = dict(pdf_template.load_mapping())
        self._page = 0
        self._page_count = max(1, pdf_template.page_count())

        self._build()
        self._reload_page()
        self._refresh_fields()

    # ------------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        hint = QLabel(
            "اختر حقلاً من القائمة ثم انقر موضعه على الورقة. "
            "ولتعديل موضع موضوع: اسحب علامته الخضراء."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        middle = QHBoxLayout()
        middle.setSpacing(12)

        # --- قائمة الحقول ---
        side = Card(spacing=8, margins=(12, 12, 12, 12))
        side.setFixedWidth(280)

        title = QLabel("الحقول")
        title.setObjectName("sectionTitle")
        side.body.addWidget(title)

        self.fields = QListWidget()
        self.fields.currentItemChanged.connect(self._on_field_selected)
        side.body.addWidget(self.fields, 1)

        self.clear_button = QPushButton("حذف موضع هذا الحقل")
        self.clear_button.clicked.connect(self._clear_current)
        side.body.addWidget(self.clear_button)

        middle.addWidget(side)

        # --- الصفحة ---
        self.canvas = PageCanvas()
        self.canvas.placed.connect(self._on_placed)
        self.canvas.picked.connect(self._select_key)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.canvas)
        middle.addWidget(self.scroll, 1)

        outer.addLayout(middle, 1)

        # --- شريط الضبط ---
        bar = QHBoxLayout()
        bar.setSpacing(8)

        bar.addWidget(QLabel("الصفحة:"))
        self.page_box = QComboBox()
        for index in range(self._page_count):
            self.page_box.addItem("صفحة %d" % (index + 1), index)
        self.page_box.currentIndexChanged.connect(self._on_page_changed)
        bar.addWidget(self.page_box)

        bar.addWidget(QLabel("حجم الخطّ:"))
        self.size_box = QSpinBox()
        self.size_box.setRange(6, 28)
        self.size_box.setValue(pdf_template.DEFAULT_FONT_SIZE)
        self.size_box.valueChanged.connect(self._on_style_changed)
        bar.addWidget(self.size_box)

        bar.addWidget(QLabel("المحاذاة:"))
        self.align_box = QComboBox()
        for value, label in pdf_template.ALIGN_LABELS.items():
            self.align_box.addItem(label, value)
        self.align_box.currentIndexChanged.connect(self._on_style_changed)
        bar.addWidget(self.align_box)

        bar.addStretch(1)

        preview = QPushButton("تجربة الطباعة")
        preview.setToolTip("يعبّئ النموذج ببيانات وهمية ويفتح الناتج للمعاينة")
        preview.clicked.connect(self._preview)
        bar.addWidget(preview)

        save = primary_button("حفظ المواضع")
        save.clicked.connect(self._save)
        bar.addWidget(save)

        close = QPushButton("إغلاق")
        close.clicked.connect(self.reject)
        bar.addWidget(close)

        outer.addLayout(bar)

    # ------------------------------------------------------------------
    def _refresh_fields(self):
        """يبني قائمة الحقول مجموعةً مجموعة، ويُعلّم المعيَّن منها."""
        self.fields.blockSignals(True)
        current = self._current_key()
        self.fields.clear()

        for group in pdf_template.FIELD_GROUPS:
            header = QListWidgetItem("— %s —" % group)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setForeground(QColor("#5a6b85"))
            self.fields.addItem(header)

            for key, label in pdf_template.fields_of_group(group):
                mapped = key in self._mapping
                item = QListWidgetItem(("✓  " if mapped else "○  ") + label)
                item.setData(Qt.ItemDataRole.UserRole, key)
                if mapped:
                    item.setForeground(QColor("#15803d"))
                self.fields.addItem(item)
                if key == current:
                    self.fields.setCurrentItem(item)

        self.fields.blockSignals(False)
        self.canvas.set_mapping(self._mapping)
        self.canvas.set_active_field(self._current_key())

    def _current_key(self):
        item = self.fields.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _select_key(self, key):
        for index in range(self.fields.count()):
            item = self.fields.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.fields.setCurrentItem(item)
                return

    # ------------------------------------------------------------------
    def _reload_page(self):
        try:
            image = pdf_template.render_page(self._page, dpi=150)
        except pdf_template.TemplateError as error:
            show_error(self, error)
            return
        self.canvas.load_page(image, self._page)
        self.canvas.set_mapping(self._mapping)
        self._fit_canvas()

    def _fit_canvas(self):
        viewport = self.scroll.viewport().height()
        if viewport > 40:
            self.canvas.fit_to_height(viewport - 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_canvas()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_canvas()

    def _on_page_changed(self, index):
        self._page = self.page_box.itemData(index) or 0
        self._reload_page()

    def _on_field_selected(self, current, previous):
        key = self._current_key()
        self.canvas.set_active_field(key)
        if not key:
            return

        spot = self._mapping.get(key)
        if not spot:
            return

        # الانتقال إلى صفحة الحقل تلقائياً: البحث عنه يدوياً إزعاج بلا فائدة
        page = int(spot.get("page", 0))
        if page != self._page:
            self.page_box.setCurrentIndex(self.page_box.findData(page))

        self.size_box.blockSignals(True)
        self.align_box.blockSignals(True)
        self.size_box.setValue(int(spot.get("size", pdf_template.DEFAULT_FONT_SIZE)))
        index = self.align_box.findData(spot.get("align", pdf_template.DEFAULT_ALIGN))
        if index >= 0:
            self.align_box.setCurrentIndex(index)
        self.size_box.blockSignals(False)
        self.align_box.blockSignals(False)

    def _on_placed(self, key, x, y):
        spot = self._mapping.setdefault(key, {})
        spot.update({
            "page": self._page,
            "x": round(x, 4),
            "y": round(y, 4),
            "size": self.size_box.value(),
            "align": self.align_box.currentData(),
        })
        self._refresh_fields()

    def _on_style_changed(self):
        key = self._current_key()
        if not key or key not in self._mapping:
            return
        self._mapping[key]["size"] = self.size_box.value()
        self._mapping[key]["align"] = self.align_box.currentData()
        self.canvas.set_mapping(self._mapping)

    def _clear_current(self):
        key = self._current_key()
        if key and key in self._mapping:
            del self._mapping[key]
            self._refresh_fields()

    # ------------------------------------------------------------------
    def _preview(self):
        if not self._mapping:
            show_error(self, "عيّن موضع حقل واحد على الأقل قبل التجربة.")
            return

        output = pathlib.Path(config.EXPORTS_DIR) / "تجربة-نموذج-العقد.pdf"
        try:
            pdf_template.fill(pdf_template.sample_values(), output,
                              mapping=self._mapping)
        except Exception as error:
            show_error(self, error)
            return

        _open_file(output)
        show_info(self, "فُتح ملف التجربة:\n%s" % output, title="تجربة الطباعة")

    def _save(self):
        try:
            pdf_template.save_mapping(self._mapping)
        except Exception as error:
            show_error(self, error)
            return
        show_info(self, "حُفظت مواضع %d حقلاً." % len(self._mapping))
        self.accept()


def _open_file(path):
    """يفتح ملفاً بالبرنامج الافتراضي في النظام."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
