"""
WorkManager - 산학협력단 담당 과제 관리 프로그램
- data/myProjects.json (크롬 확장에서 생성, 청구가능액이 능동조회 계산값으로 병합될 수 있음) 을 불러와 표로 보여줌
- data/projectType.json (확장의 '과제구분 조회'로 내보낸 결과) 이 있으면 수익/목적 과제 구분 표시
- data/mailTemplates.json 에 등록해두면 "메일 안내" 버튼에서 양식을 바로 확인 가능
- 과제별 진행상태/체크리스트/규정문서/메모/연락담당자는 data/memos.json 에 별도 저장
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QFileSystemWatcher, QTimer
from PySide6.QtGui import QColor, QBrush, QDesktopServices, QIcon
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
)

# ---------------------------------------------------------------------------
# 경로 설정 (app/main.py 기준으로 ../data/ 를 바라봄)
# ---------------------------------------------------------------------------
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
ICON_FILE = BASE_DIR / "app" / "assets" / "icon.png"  # 창/작업표시줄 아이콘

STATUS_OPTIONS = ["진행중", "종료", "완료", "보류", "검토필요"]

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


def dday_color(days):
    """마감 임박도에 따른 배경색."""
    if days is None:
        return None
    if days < 0:
        return QColor("#e5e7eb")  # 이미 지난 과제 - 회색
    if days <= 7:
        return QColor("#fecaca")  # 7일 이내 - 빨강
    if days <= 30:
        return QColor("#fed7aa")  # 30일 이내 - 주황
    return None


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


STATUS_COLORS = {
    "진행중": QColor("#dbeafe"),   # 파랑
    "종료": QColor("#e5e7eb"),     # 회색
    "완료": QColor("#dcfce7"),     # 초록
    "보류": QColor("#fef9c3"),     # 노랑
    "검토필요": QColor("#fee2e2"),  # 빨강
}

TYPE_COLORS = {
    "수익": QColor("#dbeafe"),  # 파랑
    "목적": QColor("#dcfce7"),  # 초록
}

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
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(24, 22, 24, 18)
        root_layout.setSpacing(16)

        # 상단 헤더
        header = QHBoxLayout()
        header.setSpacing(12)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title = QLabel("WorkManager")
        title.setObjectName("appTitle")
        subtitle = QLabel("산학협력단 담당 과제 관리")
        subtitle.setObjectName("appSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header.addLayout(title_box)
        header.addStretch()

        refresh_btn = QPushButton("↻  새로고침")
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.clicked.connect(self.reload_data)

        mail_btn = QPushButton("✉  메일 안내")
        mail_btn.setObjectName("primaryButton")
        mail_btn.clicked.connect(self.open_mail_templates)

        header.addWidget(refresh_btn)
        header.addWidget(mail_btn)
        root_layout.addLayout(header)

        # 검색 / 정렬 바
        control_card = QFrame()
        control_card.setObjectName("controlCard")
        control_layout = QHBoxLayout(control_card)
        control_layout.setContentsMargins(14, 10, 14, 10)
        control_layout.setSpacing(10)

        search_icon = QLabel("⌕")
        search_icon.setObjectName("searchIcon")
        control_layout.addWidget(search_icon)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("과제명, 연구책임자, 담당자로 검색")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.apply_filter)
        control_layout.addWidget(self.search_input, 1)

        sort_label = QLabel("정렬")
        sort_label.setObjectName("mutedLabel")
        control_layout.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(SORT_OPTIONS)
        self.sort_combo.currentIndexChanged.connect(self.apply_filter)
        self.sort_combo.setMinimumWidth(150)
        control_layout.addWidget(self.sort_combo)

        root_layout.addWidget(control_card)

        # 본문: 좌측 목록 + 우측 상세
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setHandleWidth(1)
        root_layout.addWidget(splitter, 1)

        # --- 좌측: 과제 목록 ---
        list_card = QFrame()
        list_card.setObjectName("panelCard")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(16, 14, 16, 10)
        list_layout.setSpacing(10)

        list_header = QHBoxLayout()
        list_title = QLabel("내 과제")
        list_title.setObjectName("sectionTitle")
        list_header.addWidget(list_title)
        list_header.addStretch()

        self.project_count_label = QLabel("0건")
        self.project_count_label.setObjectName("countBadge")
        list_header.addWidget(self.project_count_label)
        list_layout.addLayout(list_header)

        self.table = QTableWidget(0, len(TABLE_HEADERS))
        self.table.setObjectName("projectTable")
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(70)
        self.table.itemSelectionChanged.connect(self.on_row_selected)
        list_layout.addWidget(self.table)

        splitter.addWidget(list_card)

        # --- 우측: 상세 패널 ---
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.NoFrame)
        detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(20, 18, 20, 18)
        detail_layout.setSpacing(12)

        detail_heading = QHBoxLayout()
        detail_heading.setSpacing(10)
        self.detail_title = QLabel("과제를 선택하세요")
        self.detail_title.setObjectName("detailTitle")
        self.detail_title.setWordWrap(True)
        detail_heading.addWidget(self.detail_title, 1)

        self.detail_status_badge = QLabel("선택 대기")
        self.detail_status_badge.setObjectName("neutralBadge")
        detail_heading.addWidget(self.detail_status_badge, 0, Qt.AlignTop)
        detail_layout.addLayout(detail_heading)

        self.detail_info = QLabel("")
        self.detail_info.setObjectName("detailInfo")
        self.detail_info.setWordWrap(True)
        detail_layout.addWidget(self.detail_info)

        detail_layout.addWidget(self._separator())

        # 연락 담당자
        label = QLabel("연락 담당자")
        label.setObjectName("fieldLabel")
        detail_layout.addWidget(label)

        self.contact_edit = QLineEdit()
        self.contact_edit.setPlaceholderText("연락 담당자 정보를 입력하세요")
        detail_layout.addWidget(self.contact_edit)

        detail_layout.addWidget(self._separator())

        # 진행상태
        label = QLabel("진행상태")
        label.setObjectName("fieldLabel")
        detail_layout.addWidget(label)

        self.status_combo = QComboBox()
        self.status_combo.addItems(STATUS_OPTIONS)
        detail_layout.addWidget(self.status_combo)

        detail_layout.addWidget(self._separator())

        # 체크리스트
        checklist_header = QHBoxLayout()
        label = QLabel("체크리스트")
        label.setObjectName("fieldLabel")
        checklist_header.addWidget(label)
        checklist_header.addStretch()
        checklist_header.addWidget(QLabel("진행 항목을 체크하세요"))
        checklist_header.itemAt(2).widget().setObjectName("helperLabel")
        detail_layout.addLayout(checklist_header)

        self.checklist_container = QVBoxLayout()
        self.checklist_container.setSpacing(6)
        detail_layout.addLayout(self.checklist_container)

        add_preset_row = QHBoxLayout()
        self.checklist_preset_combo = QComboBox()
        self.checklist_preset_combo.addItem("자주 쓰는 항목 선택")
        self.checklist_preset_combo.addItems(PRESET_CHECKLIST_ITEMS)
        self.checklist_preset_combo.currentIndexChanged.connect(self.on_preset_selected)
        add_preset_row.addWidget(self.checklist_preset_combo)
        detail_layout.addLayout(add_preset_row)

        add_row = QHBoxLayout()
        self.new_checklist_input = QLineEdit()
        self.new_checklist_input.setPlaceholderText("새 체크리스트 항목 직접 입력")
        add_item_btn = QPushButton("＋ 추가")
        add_item_btn.setObjectName("smallPrimaryButton")
        add_item_btn.clicked.connect(self.add_checklist_item)
        add_row.addWidget(self.new_checklist_input, 1)
        add_row.addWidget(add_item_btn)
        detail_layout.addLayout(add_row)

        detail_layout.addWidget(self._separator())

        # 규정 문서
        label = QLabel("규정 문서")
        label.setObjectName("fieldLabel")
        detail_layout.addWidget(label)

        self.doc_label = QLabel("첨부된 문서 없음")
        self.doc_label.setObjectName("fileLabel")
        self.doc_label.setWordWrap(True)
        detail_layout.addWidget(self.doc_label)

        doc_btn_row = QHBoxLayout()
        pick_doc_btn = QPushButton("파일 선택")
        open_doc_btn = QPushButton("열기")
        remove_doc_btn = QPushButton("제거")
        pick_doc_btn.setObjectName("secondaryButton")
        open_doc_btn.setObjectName("secondaryButton")
        remove_doc_btn.setObjectName("ghostButton")
        pick_doc_btn.clicked.connect(self.pick_regulation_doc)
        open_doc_btn.clicked.connect(self.open_regulation_doc)
        remove_doc_btn.clicked.connect(self.remove_regulation_doc)
        doc_btn_row.addWidget(pick_doc_btn)
        doc_btn_row.addWidget(open_doc_btn)
        doc_btn_row.addWidget(remove_doc_btn)
        doc_btn_row.addStretch()
        detail_layout.addLayout(doc_btn_row)

        detail_layout.addWidget(self._separator())

        # 메모
        label = QLabel("메모")
        label.setObjectName("fieldLabel")
        detail_layout.addWidget(label)

        self.memo_edit = QTextEdit()
        self.memo_edit.setPlaceholderText("과제 관련 메모를 입력하세요.")
        self.memo_edit.setMinimumHeight(130)
        detail_layout.addWidget(self.memo_edit)

        save_btn = QPushButton("저장")
        save_btn.setObjectName("saveButton")
        save_btn.clicked.connect(self.save_current_memo)
        detail_layout.addWidget(save_btn)

        detail_layout.addStretch()
        detail_widget.setEnabled(False)
        self.detail_widget = detail_widget

        detail_scroll.setWidget(detail_widget)
        splitter.addWidget(detail_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # 상태바
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # 전체 Modern UI 스타일
        self.setStyleSheet("""
            QMainWindow {
                background: #f6f7fb;
            }
            QWidget {
                font-family: "Pretendard", "Noto Sans KR", "Malgun Gothic", sans-serif;
                font-size: 13px;
                color: #1f2937;
            }
            QToolTip {
                background: #111827;
                color: white;
                border: none;
                padding: 6px 8px;
            }

            #appTitle {
                font-size: 25px;
                font-weight: 800;
                color: #111827;
            }
            #appSubtitle {
                color: #8a94a6;
                font-size: 12px;
                font-weight: 500;
            }

            #controlCard, #panelCard {
                background: #ffffff;
                border: 1px solid #e7eaf0;
                border-radius: 14px;
            }
            #controlCard {
                min-height: 46px;
            }
            #searchIcon {
                font-size: 22px;
                color: #98a2b3;
                padding-left: 4px;
            }
            QLineEdit, QTextEdit, QComboBox {
                background: #f8f9fc;
                border: 1px solid #e5e7eb;
                border-radius: 9px;
                padding: 9px 11px;
                selection-background-color: #dbeafe;
                selection-color: #1e3a8a;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                background: #ffffff;
                border: 1px solid #93c5fd;
            }
            QComboBox {
                padding-right: 28px;
            }
            QComboBox::drop-down {
                border: none;
                width: 25px;
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                padding: 5px;
                selection-background-color: #eef2ff;
                selection-color: #1e40af;
            }

            QPushButton {
                border: none;
                border-radius: 9px;
                padding: 9px 14px;
                font-weight: 600;
            }
            #primaryButton, #smallPrimaryButton, #saveButton {
                background: #2563eb;
                color: white;
            }
            #primaryButton:hover, #smallPrimaryButton:hover, #saveButton:hover {
                background: #1d4ed8;
            }
            #secondaryButton {
                background: #eef2f7;
                color: #374151;
                border: 1px solid #e1e6ee;
            }
            #secondaryButton:hover {
                background: #e4e9f1;
            }
            #ghostButton {
                background: transparent;
                color: #6b7280;
                border: 1px solid #e5e7eb;
            }
            #ghostButton:hover {
                background: #f8fafc;
            }
            #saveButton {
                min-height: 42px;
                font-size: 14px;
                margin-top: 4px;
            }
            #smallPrimaryButton {
                padding: 8px 12px;
            }

            #sectionTitle {
                font-size: 16px;
                font-weight: 750;
                color: #111827;
            }
            #countBadge, #neutralBadge {
                background: #eef2ff;
                color: #4f46e5;
                border-radius: 12px;
                padding: 4px 9px;
                font-size: 11px;
                font-weight: 700;
            }
            #mutedLabel, #helperLabel {
                color: #98a2b3;
                font-size: 12px;
                font-weight: 500;
            }
            #fieldLabel {
                color: #344054;
                font-size: 12px;
                font-weight: 750;
                margin-top: 2px;
            }
            #fileLabel {
                background: #f8fafc;
                border: 1px dashed #d6dce6;
                border-radius: 9px;
                padding: 10px;
                color: #667085;
            }
            #detailTitle {
                font-size: 20px;
                font-weight: 800;
                color: #111827;
            }
            #detailInfo {
                color: #667085;
                line-height: 1.55;
                background: #f8fafc;
                border-radius: 10px;
                padding: 11px 13px;
            }

            #projectTable {
                background: #ffffff;
                border: none;
                outline: none;
            }
            #projectTable::item {
                border-bottom: 1px solid #f0f2f5;
                padding: 10px 8px;
            }
            #projectTable::item:selected {
                background: #eef4ff;
                color: #1d4ed8;
                border-left: 3px solid #3b82f6;
            }
            #projectTable QHeaderView::section {
                background: #fafbfc;
                color: #8a94a6;
                border: none;
                border-bottom: 1px solid #eaecf0;
                padding: 10px 8px;
                font-size: 11px;
                font-weight: 750;
            }

            QCheckBox {
                spacing: 9px;
                color: #344054;
                padding: 5px 4px;
            }
            QCheckBox::indicator {
                width: 17px;
                height: 17px;
                border-radius: 5px;
                border: 1px solid #cbd5e1;
                background: white;
            }
            QCheckBox::indicator:checked {
                background: #2563eb;
                border: 1px solid #2563eb;
            }

            QScrollBar:vertical {
                width: 8px;
                background: transparent;
                margin: 3px;
            }
            QScrollBar::handle:vertical {
                background: #d5dae3;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #b9c1ce;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
                border: none;
            }

            QStatusBar {
                background: transparent;
                color: #98a2b3;
                border: none;
                font-size: 11px;
                padding: 2px 8px;
            }
            QSplitter::handle {
                background: transparent;
            }
        """)

    @staticmethod
    def _separator():
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: #edf0f4; border: none;")
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

    def apply_filter(self):
        keyword = self.search_input.text().strip()
        filtered = [
            p
            for p in self.projects
            if keyword in p.get("과제명", "")
            or keyword in p.get("연구책임자", "")
            or keyword in p.get("담당자", "")
        ]
        sorted_projects = self.sort_projects(filtered)
        self.populate_table(sorted_projects)
        if hasattr(self, "project_count_label"):
            self.project_count_label.setText(f"{len(sorted_projects):,}건")

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
                p.get("종료일", ""),
                dday_text(days),
                status,
                ptype,
            ]

            color = dday_color(days)
            status_col_index = 5
            type_col_index = 6

            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if col == status_col_index:
                    status_color = STATUS_COLORS.get(status)
                    if status_color is not None:
                        item.setBackground(QBrush(status_color))
                elif col == type_col_index:
                    type_color = TYPE_COLORS.get(ptype)
                    if type_color is not None:
                        item.setBackground(QBrush(type_color))
                elif color is not None:
                    item.setBackground(QBrush(color))
                self.table.setItem(row, col, item)

            # 과제번호를 첫 컬럼 아이템의 UserRole에 숨겨서 저장 (조회용 키)
            self.table.item(row, 0).setData(Qt.UserRole, prj_no)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    # ---------------- 체크리스트 UI ----------------
    def rebuild_checklist_ui(self, checklist):
        """checklist: [{"항목": str, "완료": bool}, ...]"""
        while self.checklist_container.count():
            item = self.checklist_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.checklist_rows = []

        for entry in checklist:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            checkbox = QCheckBox(entry.get("항목", ""))
            checkbox.setChecked(bool(entry.get("완료", False)))
            row_layout.addWidget(checkbox)

            del_btn = QPushButton("x")
            del_btn.setFixedWidth(24)
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
        return [{"항목": name, "완료": False} for name in DEFAULT_CHECKLIST_TEMPLATE]

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
            {"항목": item_name, "완료": checkbox.isChecked()}
            for checkbox, item_name in self.checklist_rows
        ]

        if any(entry.get("항목") == name for entry in current):
            self.new_checklist_input.clear()
            self.checklist_preset_combo.setCurrentIndex(0)
            return

        current.append({"항목": name, "완료": False})
        self.rebuild_checklist_ui(current)
        self.new_checklist_input.clear()
        self.checklist_preset_combo.setCurrentIndex(0)

    def remove_checklist_item(self, name):
        checklist = [
            {"항목": item_name, "완료": checkbox.isChecked()}
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
    def on_row_selected(self):
        selected = self.table.selectedItems()
        if not selected:
            self.detail_widget.setEnabled(False)
            return

        row = selected[0].row()
        prj_no = self.table.item(row, 0).data(Qt.UserRole)
        project = next((p for p in self.projects if p.get("과제번호") == prj_no), None)
        if project is None:
            return

        self.current_prj_no = prj_no
        self.detail_widget.setEnabled(True)

        # 청구가능액: 자금현황 원천값이 있으면 항상 상세 화면에서 직접 계산한다.
        claimable_amt = claimable_amount(project)

        # 예산잔액은 종료임박 과제 팝업에서만 부분적으로 확보되는 참고용 보조 데이터
        budget_line = ""
        if "예산잔액" in project:
            budget_line = f"\n예산잔액(참고, 종료임박 목록 기준): {safe_int(project.get('예산잔액', 0)):,}원"

        ptype = self.project_type_of(project)
        ptype_display = ptype if ptype != "-" else "미조회"

        self.detail_title.setText(project.get("과제명", ""))
        self.detail_info.setText(
            f"과제번호: {project.get('과제번호', '-')}\n"
            f"연구책임자: {project.get('연구책임자', '-')}\n"
            f"지원기관: {project.get('지원기관', '-')}\n"
            f"기간: {project.get('시작일', '-')} ~ {project.get('종료일', '-')}\n"
            f"구분: {ptype_display}\n"
            f"총사업비: {safe_int(project.get('총사업비', 0)):,}원\n"
            f"청구가능액: {claimable_amt:,}원{budget_line}"
        )

        end_date = parse_yyyymmdd(project.get("종료일", ""))
        memo_entry = self.memos.get(prj_no, {})

        self.contact_edit.setText(memo_entry.get("연락담당자", ""))

        status = resolve_status(memo_entry, end_date)
        idx = self.status_combo.findText(status)
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        if hasattr(self, "detail_status_badge"):
            self.detail_status_badge.setText(status)
            status_bg = {
                "진행중": "#e8f1ff",
                "종료": "#f0f1f3",
                "완료": "#eaf8ef",
                "보류": "#fff7df",
                "검토필요": "#fff0f0",
            }.get(status, "#eef2ff")
            status_fg = {
                "진행중": "#2563eb",
                "종료": "#667085",
                "완료": "#15803d",
                "보류": "#b45309",
                "검토필요": "#dc2626",
            }.get(status, "#4f46e5")
            self.detail_status_badge.setStyleSheet(
                f"background: {status_bg}; color: {status_fg}; "
                "border-radius: 12px; padding: 4px 9px; "
                "font-size: 11px; font-weight: 700;"
            )

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
            {"항목": name, "완료": checkbox.isChecked()}
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
        self.apply_filter()  # 표의 상태 컬럼 갱신
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