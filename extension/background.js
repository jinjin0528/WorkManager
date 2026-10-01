// background.js - 서비스 워커 (chrome.downloads 등 확장 API 전용 컨텍스트)
// 역할: 과제 목록(workmanager_cachedProjects)이 갱신될 때마다 자동으로
//       myProjects.json을 다운로드한다. 팝업을 열거나 버튼을 누를 필요 없음.

let downloadTimer = null;
const DEBOUNCE_MS = 3000; // 구분/청구가능액 등 여러 병합이 연속으로 일어나므로
                           // 마지막 변경 후 3초간 잠잠하면 그때 한 번만 내보냄

function scheduleAutoExport() {
  if (downloadTimer) clearTimeout(downloadTimer);
  downloadTimer = setTimeout(runAutoExport, DEBOUNCE_MS);
}

function runAutoExport() {
  chrome.storage.local.get(
    ["workmanager_cachedProjects", "workmanager_lastExportedJson"],
    (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) return;

      const newJson = JSON.stringify(cached.projects, null, 2);

      if (newJson === result.workmanager_lastExportedJson) {
        console.log("[WorkManager] 이전 내보내기와 내용이 동일함 - 다운로드 생략");
        return;
      }

      // 서비스 워커에는 URL.createObjectURL이 없어서(Blob 방식 사용 불가),
      // data: URL로 직접 인코딩해서 다운로드해야 함
      const dataUrl =
        "data:application/json;charset=utf-8," + encodeURIComponent(newJson);

      chrome.downloads.download(
        {
          url: dataUrl,
          filename: "WorkManager/myProjects.json",
          conflictAction: "overwrite",
          saveAs: false,
        },
        () => {
          if (chrome.runtime.lastError) {
            console.log("[WorkManager] 자동 내보내기 실패:", chrome.runtime.lastError.message);
            return;
          }
          console.log(
            `[WorkManager] myProjects.json 자동 내보내기 완료 (${cached.projects.length}건, 내용 변경 감지됨)`
          );
          chrome.storage.local.set({
            workmanager_lastExportAt: new Date().toISOString(),
            workmanager_lastExportedJson: newJson,
          });
        }
      );
    }
  );
}

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  if (changes.workmanager_cachedProjects) {
    scheduleAutoExport();
  }
});