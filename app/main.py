"""
WorkManager - 산학협력단 담당 과제 관리 프로그램
- data/myProjects.json (크롬 확장에서 생성) 을 불러와 표로 보여줌
- 과제별 진행상태/체크리스트/규정문서/메모는 data/memos.json 에 별도 저장 (앱이 직접 관리)
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QBrush, QDesktopServices
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
)

# ---------------------------------------------------------------------------
# 경로 설정 (app/main.py 기준으로 ../data/ 를 바라봄)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROJECTS_FILE = DATA_DIR / "myProjects.json"
MEMOS_FILE = DATA_DIR / "memos.json"

STATUS_OPTIONS = ["진행중", "종료", "완료", "보류", "검토필요"]

# 체크리스트가 아예 없는 과제에 처음 보여줄 기본 항목 (필요 없으면 비워두고 프리셋에서 골라서 추가)
DEFAULT_CHECKLIST_TEMPLATE = []

# 자주 쓰는 체크리스트 항목 - 드롭다운에서 골라서 빠르게 추가 가능
PRESET_CHECKLIST_ITEMS = [
    "안내메일 1차 발송",
    "안내메일 2차 발송",
    "안내메일 최종 발송",
    "수입결의 - 선금",
    "수입결의 - 잔금",
    "수입결의 - 일괄정산",
    "협약서 확인",
    "정산보고서 제출",
]

TABLE_HEADERS = ["과제명", "연구책임자", "지원기관", "종료일", "D-day", "상태"]


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


STATUS_COLORS = {
    "진행중": QColor("#dbeafe"),   # 파랑
    "종료": QColor("#e5e7eb"),     # 회색
    "완료": QColor("#dcfce7"),     # 초록
    "보류": QColor("#fef9c3"),     # 노랑
    "검토필요": QColor("#fee2e2"),  # 빨강
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


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WorkManager - 담당 과제 관리")
        self.resize(1250, 700)

        self.projects = []       # myProjects.json 원본
        self.memos = {}          # 과제번호 -> {상태, 체크리스트, 규정문서, 메모, 업데이트}
        self.current_prj_no = None
        self.checklist_rows = []  # 현재 그려진 체크리스트 행 위젯들 (rebuild용)

        self._build_ui()
        self.reload_data()

    # ---------------- UI 구성 ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # 상단 툴바 영역 (검색 + 정렬 + 새로고침)
        top_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("과제명 / 연구책임자 / 담당자 검색")
        self.search_input.textChanged.connect(self.apply_filter)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(SORT_OPTIONS)
        self.sort_combo.currentIndexChanged.connect(self.apply_filter)

        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self.reload_data)

        top_bar.addWidget(QLabel("검색:"))
        top_bar.addWidget(self.search_input)
        top_bar.addWidget(QLabel("정렬:"))
        top_bar.addWidget(self.sort_combo)
        top_bar.addWidget(refresh_btn)
        root_layout.addLayout(top_bar)

        # 본문: 좌측 표 + 우측 상세 패널
        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        # --- 좌측: 과제 목록 표 ---
        self.table = QTableWidget(0, len(TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.on_row_selected)
        splitter.addWidget(self.table)

        # --- 우측: 상세 패널 (스크롤 가능) ---
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.NoFrame)

        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)

        self.detail_title = QLabel("과제를 선택하세요")
        self.detail_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.detail_title.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)

        self.detail_info = QLabel("")
        self.detail_info.setWordWrap(True)
        self.detail_info.setStyleSheet("color: #555;")
        detail_layout.addWidget(self.detail_info)

        detail_layout.addWidget(self._separator())

        # 진행상태
        detail_layout.addWidget(QLabel("진행상태"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(STATUS_OPTIONS)
        detail_layout.addWidget(self.status_combo)

        detail_layout.addWidget(self._separator())

        # 체크리스트
        detail_layout.addWidget(QLabel("체크리스트"))
        self.checklist_container = QVBoxLayout()
        detail_layout.addLayout(self.checklist_container)

        add_preset_row = QHBoxLayout()
        self.checklist_preset_combo = QComboBox()
        self.checklist_preset_combo.addItem("자주 쓰는 항목 선택...")
        self.checklist_preset_combo.addItems(PRESET_CHECKLIST_ITEMS)
        self.checklist_preset_combo.currentIndexChanged.connect(self.on_preset_selected)
        add_preset_row.addWidget(self.checklist_preset_combo)
        detail_layout.addLayout(add_preset_row)

        add_row = QHBoxLayout()
        self.new_checklist_input = QLineEdit()
        self.new_checklist_input.setPlaceholderText("체크리스트 항목 (프리셋 선택 또는 직접 입력)")
        add_item_btn = QPushButton("+")
        add_item_btn.setFixedWidth(28)
        add_item_btn.clicked.connect(self.add_checklist_item)
        add_row.addWidget(self.new_checklist_input)
        add_row.addWidget(add_item_btn)
        detail_layout.addLayout(add_row)

        detail_layout.addWidget(self._separator())

        # 규정 문서
        detail_layout.addWidget(QLabel("규정 문서"))
        self.doc_label = QLabel("첨부된 문서 없음")
        self.doc_label.setWordWrap(True)
        self.doc_label.setStyleSheet("color: #555;")
        detail_layout.addWidget(self.doc_label)

        doc_btn_row = QHBoxLayout()
        pick_doc_btn = QPushButton("파일 선택")
        pick_doc_btn.clicked.connect(self.pick_regulation_doc)
        open_doc_btn = QPushButton("열기")
        open_doc_btn.clicked.connect(self.open_regulation_doc)
        remove_doc_btn = QPushButton("제거")
        remove_doc_btn.clicked.connect(self.remove_regulation_doc)
        doc_btn_row.addWidget(pick_doc_btn)
        doc_btn_row.addWidget(open_doc_btn)
        doc_btn_row.addWidget(remove_doc_btn)
        detail_layout.addLayout(doc_btn_row)

        detail_layout.addWidget(self._separator())

        # 메모
        detail_layout.addWidget(QLabel("메모"))
        self.memo_edit = QTextEdit()
        self.memo_edit.setFixedHeight(120)
        detail_layout.addWidget(self.memo_edit)

        save_btn = QPushButton("저장")
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

    @staticmethod
    def _separator():
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #e5e7eb;")
        return line

    # ---------------- 데이터 로드/표시 ----------------
    def reload_data(self):
        self.projects = load_projects()
        self.memos = load_memos()
        self.apply_filter()

        if not self.projects:
            self.status_bar.showMessage(
                f"myProjects.json을 찾을 수 없거나 비어 있습니다. ({PROJECTS_FILE})"
            )
        else:
            self.status_bar.showMessage(
                f"과제 {len(self.projects)}건 로드됨  |  {PROJECTS_FILE}"
            )

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

    def populate_table(self, projects):
        self.table.setRowCount(0)
        self.table.setRowCount(len(projects))

        for row, p in enumerate(projects):
            prj_no = p.get("과제번호", "")
            end_date = parse_yyyymmdd(p.get("종료일", ""))
            days = calc_dday(end_date)
            memo_entry = self.memos.get(prj_no, {})
            status = resolve_status(memo_entry, end_date)

            values = [
                p.get("과제명", ""),
                p.get("연구책임자", ""),
                p.get("지원기관", ""),
                p.get("종료일", ""),
                dday_text(days),
                status,
            ]

            color = dday_color(days)
            status_col_index = len(values) - 1  # "상태"는 마지막 컬럼

            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if col == status_col_index:
                    status_color = STATUS_COLORS.get(status)
                    if status_color is not None:
                        item.setBackground(QBrush(status_color))
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
        # 기존 행 위젯 제거
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
        """memos.json에 저장된 체크리스트가 있으면 그걸, 없으면 기본 템플릿."""
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

        # 저장 파일이 아니라 "지금 화면에 떠 있는 상태"를 기준으로 추가해야
        # 저장 전에 연달아 추가해도 이전 항목이 사라지지 않음
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

        self.detail_title.setText(project.get("과제명", ""))
        self.detail_info.setText(
            f"과제번호: {project.get('과제번호', '-')}\n"
            f"연구책임자: {project.get('연구책임자', '-')}\n"
            f"지원기관: {project.get('지원기관', '-')}\n"
            f"기간: {project.get('시작일', '-')} ~ {project.get('종료일', '-')}\n"
            f"총사업비: {int(project.get('총사업비', 0) or 0):,}원\n"
            f"청구가능액: {int(project.get('청구가능액', 0) or 0):,}원"
        )

        end_date = parse_yyyymmdd(project.get("종료일", ""))
        memo_entry = self.memos.get(prj_no, {})

        status = resolve_status(memo_entry, end_date)
        idx = self.status_combo.findText(status)
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)

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
            "메모": self.memo_edit.toPlainText(),
            "업데이트": datetime.now().isoformat(timespec="seconds"),
        }
        save_memos(self.memos)
        self.apply_filter()  # 표의 상태 컬럼 갱신
        self.status_bar.showMessage("저장되었습니다.", 3000)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
