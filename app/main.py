"""
WorkManager - 산학협력단 담당 과제 관리 프로그램
- data/myProjects.json (크롬 확장에서 생성, 청구가능액이 능동조회 계산값으로 병합될 수 있음) 을 불러와 표로 보여줌
- data/projectType.json (확장의 '과제구분 조회'로 내보낸 결과) 이 있으면 수익/목적 과제 구분 표시
- data/mailTemplates.json 에 등록해두면 "메일 안내" 버튼에서 양식을 바로 확인 가능
- 과제별 진행상태/체크리스트/규정문서/메모/연락담당자는 data/memos.json 에 별도 저장
"""

import json
import math
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QUrl,
    QFileSystemWatcher,
    QTimer,
    QSize,
    QRectF,
    QPointF,
    QByteArray,
)
from PySide6.QtGui import (
    QColor,
    QBrush,
    QDesktopServices,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QFont,
    QFontMetrics,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QTextEdit,
    QSplitter,
    QHeaderView,
    QStatusBar,
    QScrollArea,
    QCheckBox,
    QFileDialog,
    QFrame,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
)

# ---------------------------------------------------------------------------
# 경로 설정 (app/main.py 기준으로 ../data/ 를 바라봄)
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    # PyInstaller로 exe 패키징된 경우: exe 파일이 있는 폴더를 기준으로 함
    # (WorkManager.exe 옆에 data/, app/assets/ 폴더가 같이 있어야 함)
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    # 일반 python main.py로 실행하는 경우: 기존처럼 app/main.py 기준 상위 폴더
    BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# 확장이 자동으로 내려받는 myProjects.json은 사용자 홈 폴더의
# Downloads\WorkManager\ 안에 항상 같은 이름으로 저장됨 (background.js 참고).
# Path.home()이 "지금 로그인한 사용자"의 홈 폴더를 자동으로 찾아주므로,
# 팀원 각자 컴퓨터에서 실행해도 경로를 따로 손볼 필요가 없음(심볼릭 링크 불필요).
DOWNLOADS_WORKMANAGER_DIR = Path.home() / "Downloads" / "WorkManager"
PROJECTS_FILE = DOWNLOADS_WORKMANAGER_DIR / "myProjects.json"

MEMOS_FILE = DATA_DIR / "memos.json"
PROJECT_TYPE_FILE = DATA_DIR / "projectType.json"  # 확장의 '과제구분 조회'로 내보낸 데이터 (구버전 호환용)
MAIL_TEMPLATES_FILE = DATA_DIR / "mailTemplates.json"  # 메일 안내 양식 목록
if getattr(sys, "frozen", False):
    ICON_FILE = BASE_DIR / "assets" / "icon.png"  # exe와 같은 폴더에 assets/ 필요
else:
    ICON_FILE = BASE_DIR / "app" / "assets" / "icon.png"  # 창/작업표시줄 아이콘

STATUS_OPTIONS = ["진행중", "종료", "정산완료", "보류"]

# 체크리스트가 아예 없는 과제에 처음 보여줄 기본 항목 (필요 없으면 비워두고 프리셋에서 골라서 추가)
DEFAULT_CHECKLIST_TEMPLATE = []

# 자주 쓰는 체크리스트 항목 - 드롭다운에서 골라서 빠르게 추가 가능
PRESET_CHECKLIST_ITEMS = [
    "과제 개시 안내메일 발송",
    "부가세 안내메일 발송",
    "과제 종료 안내메일 발송",
    "수입결의 - 선금",
    "수입결의 - 잔금",
    "수입결의 - 일괄정산",
    "협약서 확인",
    "정산보고서 제출",
]

TABLE_HEADERS = ["과제명", "연구책임자", "지원기관", "종료일", "D-day", "상태", "구분"]


# ---------------------------------------------------------------------------
# 유틸 함수
# ---------------------------------------------------------------------------
def parse_yyyymmdd(value: str):
    """'20261231' 형태의 문자열을 date 객체로 변환. 실패하면 None."""
    if not value or len(value) != 8:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def calc_dday(end_date):
    """종료일까지 남은 일수. 지났으면 음수."""
    if end_date is None:
        return None
    return (end_date - date.today()).days


def dday_text(days):
    if days is None:
        return "-"
    if days > 0:
        return f"D-{days}"
    if days == 0:
        return "D-DAY"
    return f"D+{abs(days)}"


def dday_pill(days):
    """D-day 배지 색상 (배경, 글자). 마감이 가까울수록 붉게, 여유가 있으면 초록."""
    if days is None or days < 0:
        return PILL_GRAY  # 정보 없음 / 이미 지난 과제 - 회색
    if days <= 7:
        return ("#ffe1e1", "#d93f3f")  # 7일 이내 - 빨강
    if days <= 30:
        return ("#ffe9d2", "#e0701b")  # 30일 이내 - 주황
    if days <= 90:
        return ("#fff3cf", "#c98a00")  # 90일 이내 - 노랑
    return ("#dcf5e6", "#1f9d57")      # 여유 있음 - 초록


def format_date(value, sep="-"):
    """'20261231' -> '2026-12-31'. 변환할 수 없으면 원본(또는 '-')을 그대로 반환."""
    parsed = parse_yyyymmdd(value) if isinstance(value, str) else None
    if parsed is None:
        return str(value) if value else "-"
    return parsed.strftime(f"%Y{sep}%m{sep}%d")



def default_status(end_date):
    """사용자가 상태를 따로 지정한 적 없을 때, 날짜 기준으로 자동 판정."""
    if end_date is None:
        return "진행중"
    if end_date < date.today():
        return "종료"
    return "진행중"


def resolve_status(memo_entry: dict, end_date):
    """memos.json에 저장된 상태가 있으면 그걸 쓰고, 없으면 날짜 기준 자동값."""
    saved = memo_entry.get("상태")
    if saved:
        return saved
    return default_status(end_date)


def safe_int(value):
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
            if not value or value == "-":
                return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def claimable_amount(project: dict):
    """자금현황 원천값이 있으면 협약액 - (입금액공급가액 + 입금액부가세)로 계산."""
    if "협약액" not in project:
        return safe_int(project.get("청구가능액", 0))

    agreement = safe_int(project.get("협약액", 0))
    received_supply = safe_int(project.get("입금액공급가액", 0))
    received_vat = safe_int(project.get("입금액부가세", 0))
    return agreement - (received_supply + received_vat)


# 알약(pill) 배지 색상: (배경색, 글자색)
PILL_GRAY = ("#eceff5", "#5f6b85")

STATUS_PILL = {
    "진행중": ("#dcf5e6", "#1f9d57"),   # 초록
    "종료": ("#eceff5", "#5f6b85"),     # 회색
    "정산완료": ("#dfe9ff", "#3562e0"),     # 파랑
    "보류": ("#fff1d6", "#c27a06"),     # 노랑
    "검토필요": ("#ffe1e1", "#d93f3f"),  # 빨강
}

TYPE_PILL = {
    "수익": ("#e3ecff", "#3d6be6"),  # 파랑
    "목적": ("#fbe6f6", "#c53fa5"),  # 분홍
}

PILL_COLUMNS = (4, 5, 6)  # 표에서 알약 배지로 그리는 컬럼 (D-day / 상태 / 구분)

# 진행상태 단계 표시: 과제개시 → 진행중 → 종료 → 정산완료
STATUS_STEP = {"진행중": 1, "종료": 2, "정산완료": 4, "보류": 1, "검토필요": 1}
STATUS_ACCENT = {"보류": "#f59e0b", "검토필요": "#ef4444"}  # 그 외에는 기본 파랑

PRIMARY = "#4f7cf5"
SIDEBAR_WIDTH = 232

# 사이드바 상단 메뉴 (표시 이름, 아이콘, 필터링할 상태 - None이면 전체)
NAV_STATUS_ITEMS = [
    ("전체 과제", "home", None),
    ("진행중", "clock", "진행중"),
    ("종료", "stop", "종료"),
    ("정산완료", "check_circle", "정산완료"),
    ("보류", "alert", "보류"),
    ("검토필요", "plus_square", "검토필요"),
]

SORT_OPTIONS = [
    "종료일 임박순",
    "종료일 늦은순",
    "진행중 먼저",
    "종료된 것 먼저",
]


# ---------------------------------------------------------------------------
# 데이터 로드 / 저장
# ---------------------------------------------------------------------------
def load_projects():
    if not PROJECTS_FILE.exists():
        return []
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def load_memos():
    if not MEMOS_FILE.exists():
        return {}
    try:
        with open(MEMOS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_memos(memos: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(MEMOS_FILE, "w", encoding="utf-8") as f:
        json.dump(memos, f, ensure_ascii=False, indent=2)


def load_project_types():
    """확장의 '과제구분 조회'로 내보낸 projectType.json. 없으면 빈 dict."""
    if not PROJECT_TYPE_FILE.exists():
        return {}
    try:
        with open(PROJECT_TYPE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def load_mail_templates():
    """메일 안내용 템플릿을 data/mailTemplates.json에서 불러온다."""
    if not MAIL_TEMPLATES_FILE.exists():
        return []
    try:
        with open(MAIL_TEMPLATES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# 아이콘 (SVG를 코드로 그려서 사용 - 별도 이미지 파일 불필요)
# ---------------------------------------------------------------------------
def _gear_path(cx=12.0, cy=12.0, r_out=9.6, r_in=7.4, teeth=8):
    """톱니바퀴 외곽선 SVG path를 계산해서 만든다."""
    points = []
    half = math.pi / teeth
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        for ang, r in (
            (a - half * 0.55, r_in),
            (a - half * 0.30, r_out),
            (a + half * 0.30, r_out),
            (a + half * 0.55, r_in),
        ):
            points.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in points) + " Z"


ICON_PATHS = {
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 9.5V20h14V9.5"/><path d="M10 20v-5h4v5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "stop": '<circle cx="12" cy="12" r="9"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
    "check_circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
    "alert": '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5"/><path d="M12 17.3h.01"/>',
    "plus_square": '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M12 8v8M8 12h8"/>',
    "check_square": '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M8 12l3 3 5-6"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3.5 7.5l8.5 6 8.5-6"/>',
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6M9 16h6"/>',
    "settings": f'<path d="{_gear_path()}"/><circle cx="12" cy="12" r="2.8"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "bell": '<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 21h4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 21c0-4 3.5-6 7.5-6s7.5 2 7.5 6"/>',
    "building": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2"/><path d="M10 21v-4h4v4"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    "check_mark": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
}

LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
    '<circle cx="19" cy="29" r="12" fill="#4f7cf5" fill-opacity="0.92"/>'
    '<circle cx="31" cy="17" r="11" fill="#8b6cf0" fill-opacity="0.85"/>'
    '<circle cx="31" cy="31" r="9" fill="#5cc8f5" fill-opacity="0.75"/>'
    "</svg>"
)

SPROUT_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
    '<path d="M24 44V26" stroke="#5b86f5" stroke-width="2.4" stroke-linecap="round" fill="none"/>'
    '<path d="M24 27C24 18 17 13 8 13c0 9 6 14 16 14z" fill="#8fb0fa"/>'
    '<path d="M24 22C24 13 30 8 40 8c0 9-6 14-16 14z" fill="#4f7cf5"/>'
    "</svg>"
)


def _render_svg(svg: str, width: int, height: int, scale: int = 2) -> QPixmap:
    """SVG 문자열을 (고해상도 화면에서도 선명하도록) scale배 크기의 QPixmap으로 그린다."""
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(width * scale, height * scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def svg_pixmap(name: str, color: str, size: int = 20, stroke: float = 1.8, scale: int = 2) -> QPixmap:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
        f"{ICON_PATHS[name]}</svg>"
    )
    return _render_svg(svg, size, size, scale)


def svg_icon(name: str, color: str, size: int = 20) -> QIcon:
    return QIcon(svg_pixmap(name, color, size))


def build_qss_assets() -> dict:
    """스타일시트(QSS)의 url(...)에서 쓸 체크 표시/화살표 이미지를 임시 폴더에 만들어 둔다."""
    out_dir = Path(tempfile.gettempdir()) / "WorkManager_ui"
    result = {}
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    for key, name, color, size, stroke in (
        ("check", "check_mark", "#ffffff", 14, 2.6),
        ("chevron", "chevron_down", "#7b849a", 12, 2.4),
    ):
        path = out_dir / f"{key}.png"
        try:
            svg_pixmap(name, color, size, stroke, scale=1).save(str(path), "PNG")
        except Exception:
            pass
        result[key] = path.as_posix()
    return result


# ---------------------------------------------------------------------------
# 전체 스타일시트
# ---------------------------------------------------------------------------
APP_QSS = """
QMainWindow, QWidget#root {
    background: #f5f7fc;
}
QWidget {
    font-family: "Malgun Gothic", "Segoe UI";
    font-size: 10pt;
    color: #1e2a44;
}
QToolTip {
    background: #1e2a44;
    color: #ffffff;
    border: none;
    padding: 6px 8px;
}

/* Inputs */
QLineEdit, QComboBox, QTextEdit {
    background: #ffffff;
    border: 1px solid #e3e8f2;
    border-radius: 12px;
    padding: 9px 12px;
    selection-background-color: #dfe8ff;
    selection-color: #1e2a44;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
    border: 1px solid #7fa0f8;
}
QComboBox {
    padding-right: 32px;
}
QComboBox::drop-down {
    border: none;
    width: 30px;
}
QComboBox::down-arrow {
    image: url("@CHEVRON@");
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #e3e8f2;
    padding: 4px;
    outline: none;
    selection-background-color: #eaf0ff;
    selection-color: #2f5be0;
}
QLineEdit#headerSearch {
    border: 1px solid #edf0f7;
    border-radius: 14px;
    padding: 11px 16px;
}

/* Buttons */
QPushButton {
    background: #ffffff;
    color: #3f4a66;
    border: 1px solid #e3e8f2;
    border-radius: 11px;
    padding: 8px 14px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton:hover {
    background: #f3f6ff;
    border-color: #c9d7fb;
    color: #3f6be0;
}
QPushButton:pressed {
    background: #e8efff;
}
QPushButton:disabled {
    color: #b3bacb;
    background: #f6f7fb;
    border-color: #eceff5;
}
QPushButton#primary {
    background: #4f7cf5;
    color: #ffffff;
    border: none;
}
QPushButton#primary:hover {
    background: #3f6be0;
}
QPushButton#primary:disabled {
    background: #b9c9f7;
    color: #ffffff;
}
QPushButton#outlined {
    background: #ffffff;
    color: #3562e0;
    border: 1px solid #cddafa;
}
QPushButton#outlined:hover {
    background: #f3f6ff;
    border-color: #a9c0fa;
}
QPushButton#outlined:disabled {
    color: #b3bacb;
    border-color: #e3e8f2;
    background: #f6f7fb;
}
QPushButton#iconBtn {
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 0px;
    min-height: 0px;
    color: #8b94a8;
}
QPushButton#iconBtn:hover {
    background: #eaeffb;
    color: #d93f3f;
}

/* Sidebar navigation */
QPushButton#nav {
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 11px 16px;
    text-align: left;
    color: #4a5572;
    font-weight: 600;
}
QPushButton#nav:hover {
    background: #eaeffb;
    color: #3f6be0;
}
QPushButton#nav[active="true"] {
    background: #e4ecff;
    color: #3562e0;
}

/* Table */
QTableWidget {
    background: transparent;
    border: none;
    outline: none;
    selection-background-color: #eaf0ff;
    selection-color: #1e2a44;
}
QTableWidget::item {
    padding: 0px 12px;
    border-bottom: 1px solid #f0f3f9;
}
QTableWidget::item:hover {
    background: #f6f8fd;
}
QTableWidget::item:selected {
    background: #eaf0ff;
    color: #1e2a44;
}
QHeaderView::section {
    background: #f7f9fd;
    color: #6b7590;
    border: none;
    padding: 12px 12px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: #f7f9fd;
    border: none;
}

/* Cards */
QFrame#card {
    background: #ffffff;
    border: 1px solid #edf0f7;
    border-radius: 18px;
}
QFrame#subcard {
    background: #ffffff;
    border: 1px solid #edf0f7;
    border-radius: 14px;
}
QFrame#statBlue {
    background: #f2f6ff;
    border: 1px solid #dde7fc;
    border-radius: 12px;
}
QFrame#statGreen {
    background: #eff9f4;
    border: 1px solid #d5eee0;
    border-radius: 12px;
}
QFrame#promo {
    background: #e8effe;
    border: none;
    border-radius: 16px;
}
QFrame#vline {
    background: #e9edf5;
    border: none;
}
QLabel#sectionTitle {
    color: #1e2a44;
    font-size: 11pt;
    font-weight: 700;
}
QLabel#muted {
    color: #8b94a8;
}
QLabel#statValue {
    font-size: 12pt;
    font-weight: 800;
    color: #1e2a44;
}

/* Scroll */
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #d5dcec;
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover {
    background: #b9c4de;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 9px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #d5dcec;
    border-radius: 4px;
    min-width: 32px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

QSplitter::handle {
    background: transparent;
}

/* Progress */
QProgressBar {
    background: #e9eef9;
    border: none;
    border-radius: 6px;
    min-height: 12px;
    max-height: 12px;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f7cf5, stop:1 #7aa2ff);
}

/* Checkbox */
QCheckBox {
    spacing: 10px;
    color: #3d4966;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #cfd6e6;
    border-radius: 5px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #4f7cf5;
}
QCheckBox::indicator:checked {
    background: #4f7cf5;
    border-color: #4f7cf5;
    image: url("@CHECK@");
}

QStatusBar {
    background: transparent;
    color: #8b94a8;
}
QStatusBar::item {
    border: none;
}
"""


# ---------------------------------------------------------------------------
# 커스텀 위젯
# ---------------------------------------------------------------------------
PILL_BG_ROLE = Qt.UserRole + 1
PILL_FG_ROLE = Qt.UserRole + 2


class PillDelegate(QStyledItemDelegate):
    """D-day / 상태 / 구분 셀을 둥근 알약(pill) 배지로 그려주는 delegate.
    아이템의 PILL_BG_ROLE / PILL_FG_ROLE 에 색상(hex)이 있을 때만 배지로 그린다."""

    def paint(self, painter, option, index):
        bg = index.data(PILL_BG_ROLE)
        fg = index.data(PILL_FG_ROLE)
        text = index.data(Qt.DisplayRole)
        if not bg or not fg or not text:
            super().paint(painter, option, index)
            return

        # 선택/호버 배경과 행 구분선은 기본 방식으로 먼저 그리고, 그 위에 배지만 얹는다.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont(opt.font)
        font.setPointSizeF(9.0)
        font.setBold(True)
        painter.setFont(font)

        height = 26.0
        width = min(float(opt.rect.width() - 8), QFontMetrics(font).horizontalAdvance(text) + 26.0)
        rect = QRectF(
            opt.rect.center().x() - width / 2.0,
            opt.rect.center().y() - height / 2.0,
            width,
            height,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, height / 2.0, height / 2.0)
        painter.setPen(QColor(fg))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


class StatusStepper(QWidget):
    """과제개시 → 진행중 → 종료 → 정산완료 단계 표시."""

    STEPS = ["과제개시", "진행중", "종료", "정산완료"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 1
        self._accent = QColor(PRIMARY)
        self.setMinimumHeight(68)

    def set_state(self, current: int, accent: str = PRIMARY):
        """current: 현재 단계 번호(0~3). STEPS 길이(4)면 모든 단계 정산완료로 표시."""
        self._current = current
        self._accent = QColor(accent)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        n = len(self.STEPS)
        step_w = self.width() / n
        cy = 17.0
        r = 11.0
        idle = QColor("#d3dae9")

        label_font = QFont(self.font())
        label_font.setPointSizeF(9.0)

        for i, name in enumerate(self.STEPS):
            cx = step_w * (i + 0.5)

            # 다음 단계로 이어지는 화살표 선
            if i < n - 1:
                x1 = cx + r + 12
                x2 = cx + step_w - r - 12
                p.setPen(QPen(self._accent if i < self._current else idle, 1.4))
                p.drawLine(QPointF(x1, cy), QPointF(x2, cy))
                p.drawLine(QPointF(x2 - 4, cy - 3.5), QPointF(x2, cy))
                p.drawLine(QPointF(x2 - 4, cy + 3.5), QPointF(x2, cy))

            done = i < self._current
            active = i == self._current
            if done:
                p.setPen(Qt.NoPen)
                p.setBrush(self._accent)
                p.drawEllipse(QPointF(cx, cy), r, r)
                p.setPen(QPen(QColor("#ffffff"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(Qt.NoBrush)
                p.drawPolyline(
                    [QPointF(cx - 4.5, cy + 0.5), QPointF(cx - 1.5, cy + 3.5), QPointF(cx + 4.5, cy - 3.5)]
                )
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(self._accent if active else QColor("#dfe4ef"))
                p.drawEllipse(QPointF(cx, cy), r, r)
                p.setBrush(QColor("#ffffff"))
                p.drawEllipse(QPointF(cx, cy), r - 4.5, r - 4.5)

            label_font.setBold(active)
            p.setFont(label_font)
            p.setPen(QColor("#1e2a44") if active else QColor("#6b7590"))
            p.drawText(
                QRectF(cx - step_w / 2.0, cy + r + 8, step_w, 22),
                Qt.AlignHCenter | Qt.AlignTop,
                name,
            )
        p.end()


class NavButton(QPushButton):
    """사이드바 메뉴 버튼 (아이콘 + 텍스트, 선택 시 파란 배경)."""

    def __init__(self, text: str, icon_name: str, parent=None):
        super().__init__("  " + text, parent)
        self.setObjectName("nav")
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(20, 20))
        self._icon_normal = svg_icon(icon_name, "#66708a")
        self._icon_active = svg_icon(icon_name, "#3562e0")
        self.set_active(False)

    def set_active(self, active: bool):
        self.setProperty("active", bool(active))
        self.setIcon(self._icon_active if active else self._icon_normal)
        self.style().unpolish(self)
        self.style().polish(self)


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WorkManager - 담당 과제 관리")
        self.resize(1300, 700)

        self.projects = []       # myProjects.json 원본 (청구가능액이 계산값으로 덮어써질 수 있음)
        self.memos = {}          # 과제번호 -> {상태, 체크리스트, 규정문서, 메모, 연락담당자, 업데이트}
        self.project_types = {}  # 과제번호 -> {구분, 계정단위명}
        self.current_prj_no = None
        self.checklist_rows = []  # 현재 그려진 체크리스트 행 위젯들 (rebuild용)

        self._build_ui()
        self.reload_data()
        self._setup_file_watcher()

    # ---------------- 파일 자동 감지 ----------------
    def _setup_file_watcher(self):
        """다운로드 폴더의 myProjects.json이 확장에 의해 갱신되면 자동으로 새로고침."""
        DOWNLOADS_WORKMANAGER_DIR.mkdir(parents=True, exist_ok=True)

        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.addPath(str(DOWNLOADS_WORKMANAGER_DIR))
        if PROJECTS_FILE.exists():
            self.file_watcher.addPath(str(PROJECTS_FILE))

        self._reload_debounce_timer = QTimer(self)
        self._reload_debounce_timer.setSingleShot(True)
        self._reload_debounce_timer.timeout.connect(self._on_projects_file_changed)

        self.file_watcher.directoryChanged.connect(self._schedule_auto_reload)
        self.file_watcher.fileChanged.connect(self._schedule_auto_reload)

    def _schedule_auto_reload(self, _path):
        # 파일이 다 쓰이기 전에 읽지 않도록 약간의 지연을 두고 새로고침
        self._reload_debounce_timer.start(700)

    def _on_projects_file_changed(self):
        # 파일 감시가 끊기는 경우(파일 삭제 후 재생성 등)를 대비해 다시 등록
        if PROJECTS_FILE.exists() and str(PROJECTS_FILE) not in self.file_watcher.files():
            self.file_watcher.addPath(str(PROJECTS_FILE))
        self.reload_data()
        self.status_bar.showMessage("myProjects.json 변경 감지 - 자동 새로고침됨", 3000)

    # ---------------- UI 구성 ----------------
    def _build_ui(self):
        assets = build_qss_assets()
        self.setStyleSheet(
            APP_QSS.replace("@CHECK@", assets["check"]).replace("@CHEVRON@", assets["chevron"])
        )

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(22, 16, 22, 10)
        root_layout.setSpacing(12)

        root_layout.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_sidebar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(14)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_list_card())
        splitter.addWidget(self._build_detail_card())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([860, 430])
        body.addWidget(splitter, 1)
        root_layout.addLayout(body, 1)

        # 상태바
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # 시그널 연결 (모든 위젯이 만들어진 뒤에 연결)
        self.search_input.textChanged.connect(self._on_list_search)
        self.type_filter_combo.currentIndexChanged.connect(self.apply_filter)
        self.status_filter_combo.currentIndexChanged.connect(self._on_status_filter_changed)
        self.sort_combo.currentIndexChanged.connect(self.apply_filter)
        self.status_combo.currentTextChanged.connect(self._refresh_status_visuals)
        self.table.itemSelectionChanged.connect(self.on_row_selected)
        self._sync_nav()

    # ---- 상단 헤더 (로고 / 검색 / 날짜 / 알림 / 프로필) ----
    def _build_header(self):
        header = QHBoxLayout()
        header.setSpacing(14)

        brand_box = QWidget()
        brand_box.setFixedWidth(SIDEBAR_WIDTH)
        brand_layout = QHBoxLayout(brand_box)
        brand_layout.setContentsMargins(6, 0, 0, 0)
        brand_layout.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(_render_svg(LOGO_SVG, 44, 44))
        logo.setFixedSize(44, 44)
        brand_layout.addWidget(logo)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        brand = QLabel("WorkManager")
        brand.setStyleSheet("font-size: 20px; font-weight: 800; color: #1e2a44;")
        subtitle = QLabel("연구 과제 관리 프로그램")
        subtitle.setStyleSheet("font-size: 8pt; color: #8b94a8;")
        title_col.addWidget(brand)
        title_col.addWidget(subtitle)
        brand_layout.addLayout(title_col)
        header.addWidget(brand_box)

        header.addStretch(1)

        today = date.today()
        weekday = "월화수목금토일"[today.weekday()]
        self.date_label = QLabel(f"{today.year}년 {today.month}월 {today.day}일 ({weekday})")
        self.date_label.setObjectName("muted")
        header.addWidget(self.date_label)

        # 알림 벨: 종료 임박(7일 이내) 진행중 과제가 있으면 빨간 점 표시, 클릭하면 해당 과제 위주로 보기
        self.bell_btn = QPushButton()
        self.bell_btn.setObjectName("iconBtn")
        self.bell_btn.setIcon(svg_icon("bell", "#5b6785", 22))
        self.bell_btn.setIconSize(QSize(22, 22))
        self.bell_btn.setFixedSize(42, 42)
        self.bell_btn.setCursor(Qt.PointingHandCursor)
        self.bell_btn.clicked.connect(self._on_bell_clicked)
        self.bell_dot = QLabel(self.bell_btn)
        self.bell_dot.setFixedSize(9, 9)
        self.bell_dot.move(25, 8)
        self.bell_dot.setStyleSheet("background: #ff4d4f; border-radius: 4px; border: none;")
        self.bell_dot.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.bell_dot.hide()
        header.addWidget(self.bell_btn)

        avatar = QLabel()
        avatar.setFixedSize(44, 44)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setPixmap(svg_pixmap("user", "#4f7cf5", 22))
        avatar.setStyleSheet("background: #dfe6fb; border-radius: 22px;")
        header.addWidget(avatar)
        return header

    # ---- 왼쪽 사이드바 ----
    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(4)

        self.nav_buttons = {}  # 필터 상태(None=전체) -> NavButton
        for label, icon_name, status in NAV_STATUS_ITEMS:
            btn = NavButton(label, icon_name)
            btn.clicked.connect(lambda _=False, s=status: self._on_nav_status(s))
            layout.addWidget(btn)
            self.nav_buttons[status] = btn

        layout.addSpacing(8)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #e3e8f2; border: none; margin-left: 14px; margin-right: 14px;")
        layout.addWidget(divider)
        layout.addSpacing(8)

        for label, icon_name, handler in (
            ("체크리스트", "check_square", lambda: self._goto_section(self.checklist_card)),
            ("메일 안내", "mail", self.open_mail_templates),
            ("규정 문서", "file", lambda: self._goto_section(self.doc_card)),
            ("설정", "settings", self.open_settings_dialog),
        ):
            btn = NavButton(label, icon_name)
            btn.clicked.connect(lambda _=False, h=handler: h())
            layout.addWidget(btn)

        layout.addStretch(1)

        return sidebar

    # ---- 가운데 과제 목록 카드 ----
    def _build_list_card(self):
        list_card = QFrame()
        list_card.setObjectName("card")
        layout = QVBoxLayout(list_card)
        layout.setContentsMargins(22, 20, 22, 14)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.list_title = QLabel("전체 과제")
        self.list_title.setStyleSheet("font-size: 17pt; font-weight: 800; color: #1e2a44;")
        self.list_count = QLabel("총 0건")
        self.list_count.setObjectName("muted")
        title_row.addWidget(self.list_title)
        title_row.addWidget(self.list_count, 0, Qt.AlignBottom)
        title_row.addStretch()
        layout.addLayout(title_row)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("과제명, 연구책임자, 지원기관을 검색해보세요")
        self.search_input.setMinimumHeight(42)
        self.search_input.addAction(svg_icon("search", "#8b94a8", 18), QLineEdit.LeadingPosition)
        toolbar.addWidget(self.search_input, 1)

        self.type_filter_combo = QComboBox()
        self.type_filter_combo.addItems(["전체 구분", "수익", "목적"])
        self.type_filter_combo.setMinimumHeight(42)
        self.type_filter_combo.setMinimumWidth(118)
        toolbar.addWidget(self.type_filter_combo)

        self.status_filter_combo = QComboBox()
        self.status_filter_combo.addItem("전체 상태")
        self.status_filter_combo.addItems(STATUS_OPTIONS)
        self.status_filter_combo.setMinimumHeight(42)
        self.status_filter_combo.setMinimumWidth(118)
        toolbar.addWidget(self.status_filter_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(SORT_OPTIONS)
        self.sort_combo.setMinimumHeight(42)
        self.sort_combo.setMinimumWidth(140)
        toolbar.addWidget(self.sort_combo)

        refresh_btn = QPushButton("↻  새로고침")
        refresh_btn.setObjectName("primary")
        refresh_btn.setMinimumHeight(42)
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self.reload_data)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        for col, width in zip(PILL_COLUMNS, (92, 100, 92)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
            header_item = self.table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItemDelegateForColumn(col, PillDelegate(self.table))
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.page_label = QLabel("0건")
        self.page_label.setObjectName("muted")
        footer.addWidget(self.page_label)
        footer.addStretch()
        layout.addLayout(footer)
        return list_card

    # ---- 오른쪽 상세 패널 ----
    def _build_detail_card(self):
        detail_card = QFrame()
        detail_card.setObjectName("card")
        detail_card.setMinimumWidth(390)
        card_layout = QVBoxLayout(detail_card)
        card_layout.setContentsMargins(0, 6, 0, 0)
        card_layout.setSpacing(0)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.NoFrame)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        detail_widget = QWidget()
        detail_widget.setObjectName("detailBody")
        layout = QVBoxLayout(detail_widget)
        layout.setContentsMargins(22, 16, 22, 10)
        layout.setSpacing(14)

        # 상태 / 구분 배지
        tag_row = QHBoxLayout()
        tag_row.setSpacing(8)
        self.detail_status_pill = QLabel("")
        self.detail_type_pill = QLabel("")
        tag_row.addWidget(self.detail_status_pill)
        tag_row.addWidget(self.detail_type_pill)
        tag_row.addStretch()
        layout.addLayout(tag_row)

        # 과제명 / 과제번호
        self.detail_title = QLabel("과제를 선택하세요")
        self.detail_title.setWordWrap(True)
        self.detail_title.setStyleSheet("font-weight: 800; font-size: 15pt; color: #1e2a44;")
        layout.addWidget(self.detail_title)

        self.detail_no = QLabel("")
        self.detail_no.setObjectName("muted")
        layout.addWidget(self.detail_no)

        # 연구책임자 / 지원기관 / 연구기간
        info_box = QVBoxLayout()
        info_box.setSpacing(9)
        row, self.detail_pi = self._info_row("user", "연구책임자")
        info_box.addLayout(row)
        row, self.detail_org = self._info_row("building", "지원기관")
        info_box.addLayout(row)
        row, self.detail_period = self._info_row("calendar", "연구기간")
        info_box.addLayout(row)
        layout.addLayout(info_box)

        # 협약액 / 청구가능액
        stat_row = QHBoxLayout()
        stat_row.setSpacing(10)
        card, self.stat_total_caption, self.stat_total_value = self._stat_card("statBlue", "협약액")
        stat_row.addWidget(card, 1)
        card, _caption, self.stat_claim_value = self._stat_card("statGreen", "청구가능액")
        stat_row.addWidget(card, 1)
        layout.addLayout(stat_row)

        self.budget_note = QLabel("")
        self.budget_note.setObjectName("muted")
        self.budget_note.setWordWrap(True)
        self.budget_note.hide()
        layout.addWidget(self.budget_note)

        # 간접비 카드
        indirect_card = QFrame()
        indirect_card.setObjectName("subcard")
        il = QVBoxLayout(indirect_card)
        il.setContentsMargins(18, 16, 18, 16)
        il.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        indirect_title = QLabel("간접비")
        indirect_title.setObjectName("sectionTitle")
        info_icon = QLabel()
        info_icon.setPixmap(svg_pixmap("info", "#9aa3b8", 16))
        title_row.addWidget(indirect_title)
        title_row.addWidget(info_icon)
        title_row.addStretch()
        il.addLayout(title_row)

        bar_row = QHBoxLayout()
        bar_row.setSpacing(10)
        self.indirect_progress = QProgressBar()
        self.indirect_progress.setRange(0, 100)
        self.indirect_progress.setTextVisible(False)
        self.indirect_progress.setFixedHeight(12)
        self.indirect_percent = QLabel("-")
        self.indirect_percent.setMinimumWidth(42)
        self.indirect_percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.indirect_percent.setStyleSheet("font-weight: 800; color: #3f6be0;")
        bar_row.addWidget(self.indirect_progress, 1)
        bar_row.addWidget(self.indirect_percent)
        il.addLayout(bar_row)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        col, self.indirect_total_value = self._mini_stat("간접비 총액")
        stats_row.addWidget(col, 1)
        stats_row.addWidget(self._vline())
        col, self.indirect_collected_value = self._mini_stat("간접비 징수액")
        stats_row.addWidget(col, 1)
        stats_row.addWidget(self._vline())
        col, self.indirect_remain_value = self._mini_stat("잔여 간접비")
        stats_row.addWidget(col, 1)
        il.addLayout(stats_row)

        self.indirect_label = QLabel("")
        self.indirect_label.setObjectName("muted")
        self.indirect_label.setWordWrap(True)
        self.indirect_label.hide()
        il.addWidget(self.indirect_label)
        layout.addWidget(indirect_card)

        # 진행상태 단계
        step_title = QLabel("진행상태")
        step_title.setObjectName("sectionTitle")
        layout.addWidget(step_title)
        self.stepper = StatusStepper()
        layout.addWidget(self.stepper)

        # 체크리스트 카드
        self.checklist_card = QFrame()
        self.checklist_card.setObjectName("subcard")
        cl = QVBoxLayout(self.checklist_card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(10)
        label = QLabel("주요 체크리스트")
        label.setObjectName("sectionTitle")
        cl.addWidget(label)

        self.checklist_container = QVBoxLayout()
        self.checklist_container.setSpacing(6)
        cl.addLayout(self.checklist_container)

        self.checklist_preset_combo = QComboBox()
        self.checklist_preset_combo.addItem("자주 쓰는 항목 선택")
        self.checklist_preset_combo.addItems(PRESET_CHECKLIST_ITEMS)
        self.checklist_preset_combo.currentIndexChanged.connect(self.on_preset_selected)
        cl.addWidget(self.checklist_preset_combo)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.new_checklist_input = QLineEdit()
        self.new_checklist_input.setPlaceholderText("체크리스트 직접 입력")
        add_item_btn = QPushButton("+")
        add_item_btn.setFixedWidth(40)
        add_item_btn.clicked.connect(self.add_checklist_item)
        add_row.addWidget(self.new_checklist_input)
        add_row.addWidget(add_item_btn)
        cl.addLayout(add_row)
        layout.addWidget(self.checklist_card)

        # 담당자 / 상태 변경 카드
        manage_card = QFrame()
        manage_card.setObjectName("subcard")
        ml = QVBoxLayout(manage_card)
        ml.setContentsMargins(18, 16, 18, 16)
        ml.setSpacing(8)
        label = QLabel("연락 담당자")
        label.setObjectName("sectionTitle")
        ml.addWidget(label)
        self.contact_edit = QLineEdit()
        self.contact_edit.setPlaceholderText("연락 담당자 정보를 입력하세요")
        ml.addWidget(self.contact_edit)
        ml.addSpacing(6)
        label = QLabel("진행상태 변경")
        label.setObjectName("sectionTitle")
        ml.addWidget(label)
        self.status_combo = QComboBox()
        self.status_combo.addItems(STATUS_OPTIONS)
        ml.addWidget(self.status_combo)
        layout.addWidget(manage_card)

        # 규정 문서 카드
        self.doc_card = QFrame()
        self.doc_card.setObjectName("subcard")
        dl = QVBoxLayout(self.doc_card)
        dl.setContentsMargins(18, 16, 18, 16)
        dl.setSpacing(8)
        label = QLabel("규정 문서")
        label.setObjectName("sectionTitle")
        dl.addWidget(label)
        self.doc_label = QLabel("첨부된 문서 없음")
        self.doc_label.setObjectName("muted")
        self.doc_label.setWordWrap(True)
        dl.addWidget(self.doc_label)
        doc_btn_row = QHBoxLayout()
        doc_btn_row.setSpacing(8)
        pick_doc_btn = QPushButton("파일 선택")
        pick_doc_btn.clicked.connect(self.pick_regulation_doc)
        open_doc_btn = QPushButton("열기")
        open_doc_btn.clicked.connect(self.open_regulation_doc)
        remove_doc_btn = QPushButton("제거")
        remove_doc_btn.clicked.connect(self.remove_regulation_doc)
        doc_btn_row.addWidget(pick_doc_btn)
        doc_btn_row.addWidget(open_doc_btn)
        doc_btn_row.addWidget(remove_doc_btn)
        dl.addLayout(doc_btn_row)
        layout.addWidget(self.doc_card)

        # 메모 카드
        memo_card = QFrame()
        memo_card.setObjectName("subcard")
        mel = QVBoxLayout(memo_card)
        mel.setContentsMargins(18, 16, 18, 16)
        mel.setSpacing(8)
        label = QLabel("메모")
        label.setObjectName("sectionTitle")
        mel.addWidget(label)
        self.memo_edit = QTextEdit()
        self.memo_edit.setFixedHeight(110)
        mel.addWidget(self.memo_edit)
        layout.addWidget(memo_card)

        layout.addStretch()
        detail_widget.setEnabled(False)
        self.detail_widget = detail_widget

        self.detail_scroll.setWidget(detail_widget)
        # QScrollArea가 내부 위젯 배경을 회색으로 채우는 것을 막는다.
        detail_widget.setAutoFillBackground(False)
        self.detail_scroll.viewport().setAutoFillBackground(False)
        card_layout.addWidget(self.detail_scroll, 1)

        # 하단 고정 버튼 (변경사항 저장 / 메일 안내)
        action_bar = QWidget()
        ab = QHBoxLayout(action_bar)
        ab.setContentsMargins(22, 10, 22, 18)
        ab.setSpacing(10)

        self.save_btn = QPushButton("  변경사항 저장")
        self.save_btn.setObjectName("outlined")
        self.save_btn.setIcon(svg_icon("file", "#3562e0", 18))
        self.save_btn.setIconSize(QSize(18, 18))
        self.save_btn.setMinimumHeight(46)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_current_memo)

        mail_btn = QPushButton("  메일 안내")
        mail_btn.setObjectName("primary")
        mail_btn.setIcon(svg_icon("mail", "#ffffff", 18))
        mail_btn.setIconSize(QSize(18, 18))
        mail_btn.setMinimumHeight(46)
        mail_btn.setCursor(Qt.PointingHandCursor)
        mail_btn.clicked.connect(self.open_mail_templates)

        ab.addWidget(self.save_btn, 1)
        ab.addWidget(mail_btn, 1)
        card_layout.addWidget(action_bar)
        return detail_card

    # ---- 상세 패널용 작은 조립 함수들 ----
    def _info_row(self, icon_name, caption):
        row = QHBoxLayout()
        row.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(svg_pixmap(icon_name, "#8b94a8", 18))
        icon.setFixedWidth(20)
        cap = QLabel(caption)
        cap.setObjectName("muted")
        cap.setFixedWidth(66)
        value = QLabel("-")
        value.setWordWrap(True)
        value.setStyleSheet("font-weight: 700; color: #1e2a44;")
        row.addWidget(icon)
        row.addWidget(cap)
        row.addWidget(value, 1)
        return row, value

    def _stat_card(self, object_name, caption):
        card = QFrame()
        card.setObjectName(object_name)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        cap = QLabel(caption)
        cap.setStyleSheet("font-size: 9pt; font-weight: 700; color: #4a5572;")
        value = QLabel("-")
        value.setObjectName("statValue")
        lay.addWidget(cap)
        lay.addWidget(value)
        return card, cap, value

    def _mini_stat(self, caption):
        widget = QWidget()
        lay = QVBoxLayout(widget)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        cap = QLabel(caption)
        cap.setObjectName("muted")
        cap.setStyleSheet("font-size: 8.5pt;")
        value = QLabel("-")
        value.setStyleSheet("font-weight: 700; font-size: 9.5pt; color: #1e2a44;")
        lay.addWidget(cap)
        lay.addWidget(value)
        return widget, value

    @staticmethod
    def _vline():
        line = QFrame()
        line.setObjectName("vline")
        line.setFixedWidth(1)
        return line

    @staticmethod
    def _style_pill(label, text, bg, fg):
        label.setText(text)
        label.setStyleSheet(
            f"background: {bg}; color: {fg}; border: none; border-radius: 12px; "
            "padding: 4px 14px; font-weight: 700; font-size: 9pt;"
        )
        label.setVisible(bool(text))

    def _refresh_status_visuals(self, status):
        """상태 배지와 진행상태 단계 표시를 현재 상태값에 맞춰 갱신."""
        bg, fg = STATUS_PILL.get(status, PILL_GRAY)
        self._style_pill(self.detail_status_pill, status or "", bg, fg)
        self.stepper.set_state(STATUS_STEP.get(status, 1), STATUS_ACCENT.get(status, PRIMARY))

    def _set_detail_enabled(self, enabled):
        self.detail_widget.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)

    # ---- 사이드바 / 헤더 동작 ----
    def _on_nav_status(self, status):
        """사이드바에서 상태 메뉴를 누르면 상태 필터 콤보박스를 바꾼다."""
        idx = 0 if status is None else self.status_filter_combo.findText(status)
        self.status_filter_combo.setCurrentIndex(max(idx, 0))

    def _sync_nav(self):
        key = None if self.status_filter_combo.currentIndex() <= 0 else self.status_filter_combo.currentText()
        for status, btn in self.nav_buttons.items():
            btn.set_active(status == key)

    def _on_status_filter_changed(self, _idx=None):
        self._sync_nav()
        self.apply_filter()

    def _on_list_search(self, text):
        self.apply_filter()

    def _goto_section(self, widget):
        self.detail_scroll.ensureWidgetVisible(widget, 0, 20)
        if not self.detail_widget.isEnabled():
            self.status_bar.showMessage("과제를 먼저 선택해주세요.", 3000)

    def _update_alert_badge(self):
        """종료 임박(7일 이내) 진행중 과제 수를 계산해서 알림 벨에 표시."""
        urgent = 0
        for p in self.projects:
            days = calc_dday(parse_yyyymmdd(p.get("종료일", "")))
            if days is not None and 0 <= days <= 7 and self._status_of(p) == "진행중":
                urgent += 1
        self.bell_dot.setVisible(urgent > 0)
        self.bell_btn.setToolTip(
            f"종료 임박(7일 이내) 과제 {urgent}건" if urgent else "종료 임박 과제 없음"
        )

    def _on_bell_clicked(self):
        self.sort_combo.setCurrentText("종료일 임박순")
        self._on_nav_status("진행중")
        self.status_bar.showMessage("진행중 과제를 종료일 임박순으로 표시합니다.", 3000)

    def _open_folder(self, path):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_settings_dialog(self):
        """데이터 파일 위치를 확인하고 폴더를 열 수 있는 간단한 설정 창."""
        dialog = QDialog(self)
        dialog.setWindowTitle("설정")
        dialog.resize(640, 320)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(6)

        for caption, path in (
            ("과제 데이터 (확장에서 자동 다운로드)", PROJECTS_FILE),
            ("메모 저장 파일", MEMOS_FILE),
            ("메일 양식 파일", MAIL_TEMPLATES_FILE),
        ):
            cap = QLabel(caption)
            cap.setObjectName("sectionTitle")
            value = QLabel(str(path))
            value.setObjectName("muted")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(cap)
            layout.addWidget(value)
            layout.addSpacing(6)

        layout.addStretch()
        btn_row = QHBoxLayout()
        data_btn = QPushButton("data 폴더 열기")
        data_btn.clicked.connect(lambda: self._open_folder(DATA_DIR))
        dl_btn = QPushButton("다운로드 폴더 열기")
        dl_btn.clicked.connect(lambda: self._open_folder(DOWNLOADS_WORKMANAGER_DIR))
        close_btn = QPushButton("닫기")
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(data_btn)
        btn_row.addWidget(dl_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dialog.exec()

    @staticmethod
    def _separator():
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #e5e7eb;")
        return line

    # ---------------- 메일 안내 ----------------
    def open_mail_templates(self):
        """메일 안내 버튼을 눌렀을 때 메일 양식 목록을 보여준다."""
        dialog = QDialog(self)
        dialog.setWindowTitle("메일 안내")
        dialog.resize(850, 600)

        layout = QVBoxLayout(dialog)

        templates = load_mail_templates()

        if not templates:
            empty_label = QLabel(
                "등록된 메일 양식이 없습니다.\n\n"
                f"{MAIL_TEMPLATES_FILE} 파일에 메일 양식을 등록하면 여기에 표시됩니다."
            )
            empty_label.setWordWrap(True)
            layout.addWidget(empty_label)

            close_btn = QPushButton("닫기")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            dialog.exec()
            return

        content_layout = QHBoxLayout()

        template_list = QListWidget()
        content_layout.addWidget(template_list, 1)

        right_layout = QVBoxLayout()

        subject_label = QLabel("제목")
        subject_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(subject_label)

        subject_edit = QLineEdit()
        subject_edit.setReadOnly(True)
        right_layout.addWidget(subject_edit)

        body_label = QLabel("본문")
        body_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(body_label)

        body_edit = QTextEdit()
        body_edit.setReadOnly(True)
        right_layout.addWidget(body_edit)

        content_layout.addLayout(right_layout, 3)
        layout.addLayout(content_layout)

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        def show_template(item):
            index = item.data(Qt.UserRole)
            if index is None or index >= len(templates):
                return
            template = templates[index]
            subject_edit.setText(str(template.get("제목", "")))
            body_edit.setPlainText(str(template.get("본문", "")))

        for index, template in enumerate(templates):
            name = template.get("이름") or template.get("제목") or f"메일 양식 {index + 1}"
            item = QListWidgetItem(str(name))
            item.setData(Qt.UserRole, index)
            template_list.addItem(item)

        template_list.itemClicked.connect(show_template)
        template_list.setCurrentRow(0)
        show_template(template_list.item(0))

        dialog.exec()

    # ---------------- 데이터 로드/표시 ----------------
    def reload_data(self):
        self.projects = load_projects()
        self.memos = load_memos()
        self.project_types = load_project_types()
        self.apply_filter()

        msg_parts = []
        if not self.projects:
            msg_parts.append(f"myProjects.json 없음/비어있음 ({PROJECTS_FILE})")
        else:
            msg_parts.append(f"과제 {len(self.projects)}건 로드됨")

        if self.project_types:
            msg_parts.append(f"과제구분 {len(self.project_types)}건 로드됨")
        else:
            msg_parts.append("과제구분 데이터 없음 (확장에서 내보내면 반영됩니다)")

        self.status_bar.showMessage("  |  ".join(msg_parts))

    def _status_of(self, project):
        """memos.json에 저장된 상태(없으면 날짜 기준 자동값)."""
        memo_entry = self.memos.get(project.get("과제번호", ""), {})
        return resolve_status(memo_entry, parse_yyyymmdd(project.get("종료일", "")))

    def apply_filter(self):
        keyword = self.search_input.text().strip()
        type_sel = None if self.type_filter_combo.currentIndex() <= 0 else self.type_filter_combo.currentText()
        status_sel = None if self.status_filter_combo.currentIndex() <= 0 else self.status_filter_combo.currentText()

        filtered = []
        for p in self.projects:
            if keyword and not any(
                keyword in str(p.get(key) or "")
                for key in ("과제명", "연구책임자", "지원기관", "담당자")
            ):
                continue
            if type_sel and self.project_type_of(p) != type_sel:
                continue
            if status_sel and self._status_of(p) != status_sel:
                continue
            filtered.append(p)

        sorted_projects = self.sort_projects(filtered)
        self.populate_table(sorted_projects)
        self._update_alert_badge()

    def sort_projects(self, projects):
        mode = self.sort_combo.currentText()

        def end_date_of(p):
            return parse_yyyymmdd(p.get("종료일", ""))

        def status_of(p):
            memo_entry = self.memos.get(p.get("과제번호", ""), {})
            return resolve_status(memo_entry, end_date_of(p))

        if mode == "종료일 임박순":
            return sorted(projects, key=lambda p: end_date_of(p) or date.max)
        if mode == "종료일 늦은순":
            return sorted(
                projects, key=lambda p: end_date_of(p) or date.min, reverse=True
            )
        if mode == "진행중 먼저":
            return sorted(
                projects,
                key=lambda p: (
                    0 if status_of(p) == "진행중" else 1,
                    end_date_of(p) or date.max,
                ),
            )
        if mode == "종료된 것 먼저":
            return sorted(
                projects,
                key=lambda p: (
                    0 if status_of(p) == "종료" else 1,
                    end_date_of(p) or date.max,
                ),
            )
        return projects

    def project_type_of(self, project):
        """myProjects.json에 병합된 '구분' 필드를 우선 사용.
        (예전 방식인 별도 projectType.json 파일도 참고용으로 폴백 지원)"""
        merged = project.get("구분")
        if merged:
            return merged

        entry = self.project_types.get(project.get("과제번호", ""))
        if not entry or entry.get("조회실패"):
            return "-"
        return entry.get("구분", "-")

    def populate_table(self, projects):
        self.table.setRowCount(0)
        self.table.setRowCount(len(projects))

        name_brush = QBrush(QColor("#1e2a44"))
        date_brush = QBrush(QColor("#4f7cf5"))
        body_brush = QBrush(QColor("#3d4966"))

        for row, p in enumerate(projects):
            prj_no = p.get("과제번호", "")
            end_date = parse_yyyymmdd(p.get("종료일", ""))
            days = calc_dday(end_date)
            memo_entry = self.memos.get(prj_no, {})
            status = resolve_status(memo_entry, end_date)
            ptype = self.project_type_of(p)

            values = [
                p.get("과제명", ""),
                p.get("연구책임자", ""),
                p.get("지원기관", ""),
                format_date(p.get("종료일", "")),
                dday_text(days),
                status,
                ptype,
            ]

            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if col in PILL_COLUMNS:
                    item.setTextAlignment(Qt.AlignCenter)
                    if str(val) not in ("", "-"):
                        if col == 4:
                            bg, fg = dday_pill(days)
                        elif col == 5:
                            bg, fg = STATUS_PILL.get(status, PILL_GRAY)
                        else:
                            bg, fg = TYPE_PILL.get(ptype, PILL_GRAY)
                        item.setData(PILL_BG_ROLE, bg)
                        item.setData(PILL_FG_ROLE, fg)
                elif col == 0:
                    item.setForeground(name_brush)
                elif col == 3:
                    item.setForeground(date_brush)
                else:
                    item.setForeground(body_brush)
                self.table.setItem(row, col, item)

            # 과제번호를 첫 컬럼 아이템의 UserRole에 숨겨서 저장 (조회용 키)
            self.table.item(row, 0).setData(Qt.UserRole, prj_no)

        # 목록 제목 / 건수 / 하단 범위 표시
        if self.status_filter_combo.currentIndex() <= 0:
            self.list_title.setText("전체 과제")
        else:
            self.list_title.setText(f"{self.status_filter_combo.currentText()} 과제")
        total = len(projects)
        self.list_count.setText(f"총 {total}건")
        self.page_label.setText(f"1 - {total} / {total}" if total else "표시할 과제가 없습니다")

    def _select_row_by_prj_no(self, prj_no):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == prj_no:
                self.table.selectRow(row)
                return

    # ---------------- 체크리스트 UI ----------------
    def rebuild_checklist_ui(self, checklist):
        """checklist: [{"항목": str, "정산완료": bool}, ...]"""
        while self.checklist_container.count():
            item = self.checklist_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.checklist_rows = []

        for entry in checklist:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(6)

            checkbox = QCheckBox(entry.get("항목", ""))
            checkbox.setChecked(bool(entry.get("정산완료", False)))
            row_layout.addWidget(checkbox, 1)

            del_btn = QPushButton("×")
            del_btn.setObjectName("iconBtn")
            del_btn.setFixedSize(26, 26)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setToolTip("항목 삭제")
            del_btn.clicked.connect(
                lambda _, name=entry.get("항목", ""): self.remove_checklist_item(name)
            )
            row_layout.addWidget(del_btn)

            self.checklist_container.addWidget(row_widget)
            self.checklist_rows.append((checkbox, entry.get("항목", "")))

    def get_current_checklist(self):
        memo_entry = self.memos.get(self.current_prj_no, {})
        checklist = memo_entry.get("체크리스트")
        if checklist:
            return checklist
        return [{"항목": name, "정산완료": False} for name in DEFAULT_CHECKLIST_TEMPLATE]

    def on_preset_selected(self, idx):
        if idx <= 0:
            return
        text = self.checklist_preset_combo.itemText(idx)
        self.new_checklist_input.setText(text)

    def add_checklist_item(self):
        if not self.current_prj_no:
            return
        name = self.new_checklist_input.text().strip()
        if not name:
            return

        current = [
            {"항목": item_name, "정산완료": checkbox.isChecked()}
            for checkbox, item_name in self.checklist_rows
        ]

        if any(entry.get("항목") == name for entry in current):
            self.new_checklist_input.clear()
            self.checklist_preset_combo.setCurrentIndex(0)
            return

        current.append({"항목": name, "정산완료": False})
        self.rebuild_checklist_ui(current)
        self.new_checklist_input.clear()
        self.checklist_preset_combo.setCurrentIndex(0)

    def remove_checklist_item(self, name):
        checklist = [
            {"항목": item_name, "정산완료": checkbox.isChecked()}
            for checkbox, item_name in self.checklist_rows
            if item_name != name
        ]
        self.rebuild_checklist_ui(checklist)

    # ---------------- 규정 문서 ----------------
    def pick_regulation_doc(self):
        if not self.current_prj_no:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "규정 문서 선택", str(BASE_DIR), "PDF 파일 (*.pdf)"
        )
        if path:
            self.current_doc_path = path
            self.doc_label.setText(Path(path).name)

    def open_regulation_doc(self):
        path = getattr(self, "current_doc_path", None)
        if not path:
            self.status_bar.showMessage("첨부된 문서가 없습니다.", 3000)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def remove_regulation_doc(self):
        self.current_doc_path = None
        self.doc_label.setText("첨부된 문서 없음")

    # ---------------- 상세 패널 ----------------
    def update_indirect_cost_display(self, project):
        total = project.get("간접비총액")
        collected = project.get("간접비징수액")
        ratio = project.get("간접비진행률")

        def show_empty(message):
            self.indirect_progress.setValue(0)
            self.indirect_percent.setText("-")
            self.indirect_total_value.setText("-")
            self.indirect_collected_value.setText("-")
            self.indirect_remain_value.setText("-")
            self.indirect_label.setText(message)
            self.indirect_label.show()

        if total is None or collected is None:
            show_empty("아직 조회되지 않았습니다. (확장에서 자동 조회됨)")
            return

        total = safe_int(total)
        collected = safe_int(collected)

        if total <= 0:
            show_empty("이 과제는 간접비 확인 되지 않습니다.")
            return

        percent = int(round((ratio if ratio is not None else collected / total) * 100))
        percent = max(0, min(100, percent))

        self.indirect_progress.setValue(percent)
        self.indirect_percent.setText(f"{percent}%")
        self.indirect_total_value.setText(f"{total:,}원")
        self.indirect_collected_value.setText(f"{collected:,}원")
        self.indirect_remain_value.setText(f"{max(total - collected, 0):,}원")
        self.indirect_label.hide()

    def on_row_selected(self):
        selected = self.table.selectedItems()
        if not selected:
            self._set_detail_enabled(False)
            return

        row = selected[0].row()
        prj_no = self.table.item(row, 0).data(Qt.UserRole)
        project = next((p for p in self.projects if p.get("과제번호") == prj_no), None)
        if project is None:
            return

        self.current_prj_no = prj_no
        self._set_detail_enabled(True)

        # 청구가능액: 자금현황 원천값이 있으면 항상 상세 화면에서 직접 계산한다.
        claimable_amt = claimable_amount(project)

        ptype = self.project_type_of(project)

        self.detail_title.setText(project.get("과제명", ""))
        self.detail_no.setText(f"과제번호 {project.get('과제번호', '-')}")
        self.detail_pi.setText(str(project.get("연구책임자") or "-"))
        self.detail_org.setText(str(project.get("지원기관") or "-"))
        self.detail_period.setText(
            f"{format_date(project.get('시작일', ''), '.')} ~ {format_date(project.get('종료일', ''), '.')}"
        )

        # 협약액 (값이 없으면 총사업비로 대체해서 캡션도 함께 바꾼다)
        if "협약액" in project:
            self.stat_total_caption.setText("협약액")
            self.stat_total_value.setText(f"{safe_int(project.get('협약액', 0)):,}원")
        else:
            self.stat_total_caption.setText("총사업비")
            self.stat_total_value.setText(f"{safe_int(project.get('총사업비', 0)):,}원")
        self.stat_claim_value.setText(f"{claimable_amt:,}원")

        # 예산잔액은 종료임박 과제 팝업에서만 부분적으로 확보되는 참고용 보조 데이터
        if "예산잔액" in project:
            self.budget_note.setText(
                f"예산잔액(참고, 종료임박 목록 기준): {safe_int(project.get('예산잔액', 0)):,}원"
            )
            self.budget_note.show()
        else:
            self.budget_note.hide()

        end_date = parse_yyyymmdd(project.get("종료일", ""))
        memo_entry = self.memos.get(prj_no, {})

        # 구분 배지
        if ptype and ptype != "-":
            bg, fg = TYPE_PILL.get(ptype, PILL_GRAY)
            self._style_pill(self.detail_type_pill, ptype, bg, fg)
        else:
            self._style_pill(self.detail_type_pill, "구분 미조회", *PILL_GRAY)

        self.update_indirect_cost_display(project)

        self.contact_edit.setText(memo_entry.get("연락담당자", ""))

        status = resolve_status(memo_entry, end_date)
        idx = self.status_combo.findText(status)
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._refresh_status_visuals(self.status_combo.currentText())

        self.rebuild_checklist_ui(self.get_current_checklist())

        self.current_doc_path = memo_entry.get("규정문서")
        self.doc_label.setText(
            Path(self.current_doc_path).name if self.current_doc_path else "첨부된 문서 없음"
        )

        self.memo_edit.setPlainText(memo_entry.get("메모", ""))

    def save_current_memo(self):
        if not self.current_prj_no:
            return

        checklist = [
            {"항목": name, "정산완료": checkbox.isChecked()}
            for checkbox, name in self.checklist_rows
        ]

        self.memos[self.current_prj_no] = {
            "상태": self.status_combo.currentText(),
            "체크리스트": checklist,
            "규정문서": getattr(self, "current_doc_path", None),
            "연락담당자": self.contact_edit.text().strip(),
            "메모": self.memo_edit.toPlainText(),
            "업데이트": datetime.now().isoformat(timespec="seconds"),
        }
        save_memos(self.memos)

        prj_no = self.current_prj_no
        self.apply_filter()  # 표의 상태 컬럼 갱신 (표가 다시 그려지면 선택이 풀리므로 아래에서 복원)
        self._select_row_by_prj_no(prj_no)
        self.status_bar.showMessage("저장되었습니다.", 3000)


def main():
    # Windows에서 작업표시줄 아이콘이 python.exe 기본 아이콘으로 뜨는 문제 방지
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "WorkManager.GachonSanhak.1.0"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)

    if ICON_FILE.exists():
        icon = QIcon(str(ICON_FILE))
        app.setWindowIcon(icon)

    window = MainWindow()

    if ICON_FILE.exists():
        window.setWindowIcon(icon)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()