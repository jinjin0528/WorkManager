document.addEventListener("DOMContentLoaded", () => {
  const nameInput = document.getElementById("nameInput");
  const saveBtn = document.getElementById("saveBtn");
  const status = document.getElementById("status");
  const cacheBox = document.getElementById("cacheBox");
  const exportBtn = document.getElementById("exportBtn");

  // 저장된 이름 불러오기
  chrome.storage.local.get(["workmanager_userName"], (result) => {
    if (result.workmanager_userName) {
      nameInput.value = result.workmanager_userName;
    }
  });

  // 캐시된 과제 데이터 상태 표시
  function refreshCacheStatus() {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) {
        cacheBox.innerHTML = '<span class="empty">아직 감지된 과제 데이터가 없습니다.</span>';
        exportBtn.disabled = true;
        return;
      }

      const time = new Date(cached.updatedAt).toLocaleString("ko-KR");
      cacheBox.innerHTML = `
        <b>${cached.userName}</b> 담당 과제 <b>${cached.projects.length}건</b> 감지됨<br>
        (마지막 갱신: ${time})
      `;
      exportBtn.disabled = false;
    });
  }

  refreshCacheStatus();

  saveBtn.addEventListener("click", () => {
    const name = nameInput.value.trim();

    if (!name) {
      status.style.color = "#dc2626";
      status.textContent = "이름을 입력해주세요.";
      return;
    }

    chrome.storage.local.set({ workmanager_userName: name }, () => {
      status.style.color = "#16a34a";
      status.textContent = `"${name}" 저장 완료`;
    });
  });

  exportBtn.addEventListener("click", () => {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) return;

      const blob = new Blob([JSON.stringify(cached.projects, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);

      chrome.downloads.download(
        {
          url: url,
          filename: "myProjects.json",
          conflictAction: "overwrite",
          saveAs: false,
        },
        () => {
          status.style.color = "#16a34a";
          status.textContent = `myProjects.json 다운로드 완료 (${cached.projects.length}건)`;
        }
      );
    });
  });
});