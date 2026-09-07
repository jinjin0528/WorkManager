"""
WorkManager - 산학협력단 담당 과제 관리 프로그램
- data/myProjects.json (크롬 확장에서 생성) 을 불러와 표로 보여줌
- 과제별 진행상태/메모는 data/memos.json 에 별도 저장 (앱이 직접 관리)
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
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
    QMessageBox,
    QHeaderView,
    QStatusBar,
)

# ---------------------------------------------------------------------------
# 경로 설정 (app/main.py 기준으로 ../data/ 를 바라봄)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROJECTS_FILE = DATA_DIR / "myProjects.json"
MEMOS_FILE = DATA_DIR / "memos.json"

STATUS_OPTIONS = ["진행중", "완료", "보류", "검토필요"]

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
        self.resize(1100, 650)

        self.projects = []       # myProjects.json 원본
        self.memos = {}          # 과제번호 -> {상태, 메모, 업데이트}
        self.current_prj_no = None

        self._build_ui()
        self.reload_data()

    # ---------------- UI 구성 ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # 상단 툴바 영역 (검색 + 새로고침)
        top_bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("과제명 / 연구책임자 검색")
        self.search_input.textChanged.connect(self.apply_filter)

        refresh_btn = QPushButton("새로고침")
        refresh_btn.clicked.connect(self.reload_data)

        top_bar.addWidget(QLabel("검색:"))
        top_bar.addWidget(self.search_input)
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

        # --- 우측: 상세/메모 패널 ---
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

        detail_layout.addWidget(QLabel("진행상태"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(STATUS_OPTIONS)
        detail_layout.addWidget(self.status_combo)

        detail_layout.addWidget(QLabel("메모"))
        self.memo_edit = QTextEdit()
        detail_layout.addWidget(self.memo_edit)

        save_btn = QPushButton("저장")
        save_btn.clicked.connect(self.save_current_memo)
        detail_layout.addWidget(save_btn)

        detail_layout.addStretch()
        detail_widget.setEnabled(False)
        self.detail_widget = detail_widget

        splitter.addWidget(detail_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # 상태바
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

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
            if keyword in p.get("과제명", "") or keyword in p.get("연구책임자", "")
        ]
        self.populate_table(filtered)

    def populate_table(self, projects):
        self.table.setRowCount(0)
        self.table.setRowCount(len(projects))

        for row, p in enumerate(projects):
            prj_no = p.get("과제번호", "")
            end_date = parse_yyyymmdd(p.get("종료일", ""))
            days = calc_dday(end_date)
            memo_entry = self.memos.get(prj_no, {})
            status = memo_entry.get("상태", STATUS_OPTIONS[0])

            values = [
                p.get("과제명", ""),
                p.get("연구책임자", ""),
                p.get("지원기관", ""),
                p.get("종료일", ""),
                dday_text(days),
                status,
            ]

            color = dday_color(days)

            for col, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                if color is not None:
                    item.setBackground(QBrush(color))
                self.table.setItem(row, col, item)

            # 과제번호를 첫 컬럼 아이템의 UserRole에 숨겨서 저장 (조회용 키)
            self.table.item(row, 0).setData(Qt.UserRole, prj_no)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

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

        memo_entry = self.memos.get(prj_no, {})
        status = memo_entry.get("상태", STATUS_OPTIONS[0])
        idx = self.status_combo.findText(status)
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.memo_edit.setPlainText(memo_entry.get("메모", ""))

    def save_current_memo(self):
        if not self.current_prj_no:
            return

        self.memos[self.current_prj_no] = {
            "상태": self.status_combo.currentText(),
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
