document.addEventListener("DOMContentLoaded", () => {
  const nameInput = document.getElementById("nameInput");
  const saveBtn = document.getElementById("saveBtn");
  const refreshBtn = document.getElementById("refreshBtn");
  const status = document.getElementById("status");
  const cacheBox = document.getElementById("cacheBox");

  chrome.storage.local.get(["workmanager_userName"], (result) => {
    if (result.workmanager_userName) {
      nameInput.value = result.workmanager_userName;
    }
  });

  function refreshCacheStatus() {
    chrome.storage.local.get(
      ["workmanager_cachedProjects", "workmanager_lastExportAt"],
      (result) => {
        const cached = result.workmanager_cachedProjects;
        if (!cached || !cached.projects || cached.projects.length === 0) {
          cacheBox.innerHTML = '<span class="empty">아직 감지된 과제 데이터가 없습니다.</span>';
          return;
        }

        const withType = cached.projects.filter((p) => p.구분).length;
        const withClaimable = cached.projects.filter((p) => "청구가능액" in p).length;
        const detectedTime = new Date(cached.updatedAt).toLocaleString("ko-KR");
        const exportLine = result.workmanager_lastExportAt
          ? `파일 저장됨: ${new Date(result.workmanager_lastExportAt).toLocaleString("ko-KR")}`
          : "파일 저장 대기 중";

        cacheBox.innerHTML = `
          <b>${cached.userName}</b> 담당 과제 <b>${cached.projects.length}건</b> 감지됨<br>
          구분 확인됨: ${withType}건 / 청구가능액 반영: ${withClaimable}건<br>
          (감지 시각: ${detectedTime})<br>
          ${exportLine}
        `;
      }
    );
  }

  refreshCacheStatus();
  setInterval(refreshCacheStatus, 2000);

  function clearCacheAndReload(onDone) {
    chrome.storage.local.remove(
      [
        "workmanager_cachedProjects",
        "workmanager_budgetMap",
        "workmanager_claimableMap",
        "workmanager_projectType",
        "workmanager_projectTypeMap",
        "workmanager_lastExportedJson",
        "workmanager_lastExportAt",
      ],
      () => {
        chrome.tabs.query(
          { url: ["https://portal.gachon.ac.kr/*", "https://gusanhak.gachon.ac.kr/*"] },
          (tabs) => {
            if (tabs.length === 0) {
              status.style.color = "#dc2626";
              status.textContent = "열려있는 ERP/포털 탭이 없습니다. 먼저 ERP에 접속해주세요.";
            } else {
              tabs.forEach((tab) => chrome.tabs.reload(tab.id));
            }
            refreshCacheStatus();
            if (onDone) onDone();
          }
        );
      }
    );
  }

  saveBtn.addEventListener("click", () => {
    const name = nameInput.value.trim();
    if (!name) {
      status.style.color = "#dc2626";
      status.textContent = "이름을 입력해주세요.";
      return;
    }

    chrome.storage.local.get(["workmanager_userName"], (prevResult) => {
      const prevName = prevResult.workmanager_userName;
      const nameChanged = prevName !== name;

      chrome.storage.local.set({ workmanager_userName: name }, () => {
        if (!nameChanged) {
          status.style.color = "#16a34a";
          status.textContent = `"${name}" 저장 완료`;
          return;
        }

        // 이름이 바뀌면 예전 캐시(다른 사람 기준으로 필터링된 데이터)는
        // 더 이상 유효하지 않으므로 전부 비우고 ERP를 새로고침해서 즉시 재감지
        status.style.color = "#16a34a";
        status.textContent = `"${name}" 저장 완료 - ERP 페이지 새로고침 중`;
        clearCacheAndReload();
      });
    });
  });

  refreshBtn.addEventListener("click", () => {
    status.style.color = "#2563eb";
    status.textContent = "캐시를 비우고 ERP 페이지를 새로고침합니다.";
    clearCacheAndReload(() => {
      status.textContent = "새로고침 완료. 잠시 후 자동으로 다시 감지됩니다.";
    });
  });
});