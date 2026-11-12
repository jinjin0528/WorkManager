// background.js - 서비스 워커 (chrome.downloads 등 확장 API 전용 컨텍스트)
// 역할:
//  1) 과제 목록(workmanager_cachedProjects)이 갱신될 때마다 자동으로
//     myProjects.json을 다운로드한다.
//  2) 수입결의 대기 입금 매칭 결과(workmanager_incomeAlerts)가 갱신될 때마다
//     자동으로 incomeAlerts.json을 다운로드한다.
// 두 파일을 분리한 이유: incomeAlerts는 "특정 과제의 확정 데이터"가 아니라
// "이 지원기관에서 입금이 있었다"는 참고 신호일 뿐이라 myProjects.json(과제
// 레코드)과 절대 섞이면 안 됨 - 같은 지원기관에 과제가 여러 개면 실제로는
// 다른 과제 몫일 수도 있기 때문.
// 팝업을 열거나 버튼을 누를 필요 없이 전부 자동으로 처리됨.

const DEBOUNCE_MS = 3000; // 구분/청구가능액 등 여러 병합이 연속으로 일어나므로
                           // 마지막 변경 후 3초간 잠잠하면 그때 한 번만 내보냄

// storageKey가 바뀔 때마다 그 값을 filename으로 자동 다운로드하는 공용 내보내기기
function createAutoExporter({ storageKey, lastJsonKey, lastAtKey, filename, extractData, label }) {
  let timer = null;

  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(run, DEBOUNCE_MS);
  }

  function run() {
    chrome.storage.local.get([storageKey, lastJsonKey], (result) => {
      const stored = result[storageKey];
      const data = extractData(stored);
      if (data === undefined) return; // 아직 데이터 없음 - 내보낼 것 없음

      const newJson = JSON.stringify(data, null, 2);
      if (newJson === result[lastJsonKey]) {
        console.log(`[WorkManager] ${label}: 업데이트 내역 없음`);
        return;
      }

      // 서비스 워커에는 URL.createObjectURL이 없어서(Blob 방식 사용 불가),
      // data: URL로 직접 인코딩해서 다운로드해야 함
      const dataUrl = "data:application/json;charset=utf-8," + encodeURIComponent(newJson);

      chrome.downloads.download(
        { url: dataUrl, filename: `WorkManager/${filename}`, conflictAction: "overwrite", saveAs: false },
        () => {
          if (chrome.runtime.lastError) {
            console.log(`[WorkManager] ${label} 자동 내보내기 실패:`, chrome.runtime.lastError.message);
            return;
          }
          console.log(`[WorkManager] ${filename} 자동 내보내기 완료 (${label}, 내용 변경 감지됨)`);
          chrome.storage.local.set({
            [lastAtKey]: new Date().toISOString(),
            [lastJsonKey]: newJson,
          });
        }
      );
    });
  }

  return { schedule };
}

const projectsExporter = createAutoExporter({
  storageKey: "workmanager_cachedProjects",
  lastJsonKey: "workmanager_lastExportedJson",
  lastAtKey: "workmanager_lastExportAt",
  filename: "myProjects.json",
  label: "과제 목록",
  extractData: (cached) =>
    cached && cached.projects && cached.projects.length > 0 ? cached.projects : undefined,
});

const incomeAlertsExporter = createAutoExporter({
  storageKey: "workmanager_incomeAlerts",
  lastJsonKey: "workmanager_lastIncomeAlertsJson",
  lastAtKey: "workmanager_lastIncomeAlertsExportAt",
  filename: "incomeAlerts.json",
  label: "수입결의 대기 매칭",
  extractData: (stored) => (stored && stored.data !== undefined ? stored.data : undefined),
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  if (changes.workmanager_cachedProjects) {
    projectsExporter.schedule();
  }
  if (changes.workmanager_incomeAlerts) {
    incomeAlertsExporter.schedule();
  }
});