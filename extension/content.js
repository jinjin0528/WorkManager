// content.js - isolated world (chrome.* API 사용 가능)
// 역할: inject.js가 postMessage로 보낸 과제 목록 데이터를 받아서
//       "내 이름"으로 필터링 후 storage에 "임시 저장"만 해둔다.
//       실제 파일 다운로드는 popup에서 사용자가 버튼을 눌러야 실행됨.

console.log("=================================");
console.log("WorkManager Extension 시작");
console.log("현재 페이지:", location.href);
console.log("=================================");

window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (!event.data || event.data.source !== "workmanager-inject") return;
  if (event.data.type !== "PROJECT_LIST_DATA") return;

  const data = event.data.payload;

  chrome.storage.local.get(["workmanager_userName"], (nameResult) => {
    const myName = nameResult.workmanager_userName;

    if (!myName) {
      console.log(
        "[WorkManager] 이름이 설정되지 않았습니다. 확장 아이콘을 눌러 이름을 입력해주세요."
      );
      return;
    }

    const myProjects = data.REC.filter((p) => p.PRJ_CHRG_GRP_NM === myName);

    console.log(`[WorkManager] "${myName}" 담당 과제 ${myProjects.length}건 감지됨`);

    // 감지될 때마다 파일로 즉시 저장하지 않고,
    // "이번에 감지된 결과 중 가장 건수가 많은 것"만 storage에 보관.
    // (500건 잘림 목록에서 잡힌 2건보다, 검색으로 잡힌 40건이 더 신뢰도 높은 결과이므로
    //  더 적은 건수로는 기존 저장값을 덮어쓰지 않는다)
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      const cachedCount = cached ? cached.projects.length : -1;

      if (myProjects.length <= cachedCount) {
        console.log(
          `[WorkManager] 기존 캐시(${cachedCount}건)보다 적거나 같아 무시함`
        );
        return;
      }

      const simplified = myProjects.map((p) => ({
        과제번호: p.PRJ_NO,
        과제명: p.PRJ_NM,
        연구책임자: p.PRJ_RSPR_EMP_NM,
        담당자: p.PRJ_CHRG_GRP_NM,
        시작일: p.RCH_ST_DT,
        종료일: p.RCH_END_DT,
        지원기관: p.SUP_ORG_NM,
        총사업비: p.TOT_CASH_AMT,
        청구가능액: p.INQ_REQ_POSS_AMT,
      }));

      chrome.storage.local.set(
        {
          workmanager_cachedProjects: {
            projects: simplified,
            updatedAt: new Date().toISOString(),
            userName: myName,
          },
        },
        () => {
          console.log(
            `[WorkManager] 캐시 갱신됨: ${simplified.length}건 (팝업에서 내보내기 가능)`
          );
        }
      );
    });
  });
});

// -------------------------------------------------------------------
// 수입결의 상태 / 자금현황 조회 - popup에서 요청 오면, 캐시된 과제 목록을
// inject.js(MAIN world)로 넘겨서 백그라운드 조회 시작
// -------------------------------------------------------------------
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "START_INCOME_CHECK") {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) {
        console.log("[WorkManager] 조회할 과제 목록이 없습니다. 먼저 과제 목록을 감지해주세요.");
        return;
      }

      console.log(`[WorkManager] 수입결의 조회 요청 전달 (${cached.projects.length}건)`);
      window.postMessage(
        {
          source: "workmanager-content",
          type: "FETCH_INCOME_STATUS",
          payload: cached.projects,
        },
        "*"
      );
    });
    sendResponse({ started: true });
    return true;
  }

  if (message.type === "START_FUND_CHECK") {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) {
        console.log("[WorkManager] 조회할 과제 목록이 없습니다. 먼저 과제 목록을 감지해주세요.");
        return;
      }

      console.log(`[WorkManager] 자금현황 조회 요청 전달 (${cached.projects.length}건)`);
      window.postMessage(
        {
          source: "workmanager-content",
          type: "FETCH_FUND_STATUS",
          payload: cached.projects,
        },
        "*"
      );
    });
    sendResponse({ started: true });
    return true;
  }

  if (message.type === "START_PROJECT_TYPE_CHECK") {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) {
        console.log("[WorkManager] 조회할 과제 목록이 없습니다. 먼저 과제 목록을 감지해주세요.");
        return;
      }

      console.log(`[WorkManager] 과제구분 조회 요청 전달 (${cached.projects.length}건)`);
      window.postMessage(
        {
          source: "workmanager-content",
          type: "FETCH_PROJECT_TYPE",
          payload: cached.projects,
        },
        "*"
      );
    });
    sendResponse({ started: true });
    return true;
  }
});

// inject.js가 조회를 마치고 돌려준 결과를 저장
window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (!event.data || event.data.source !== "workmanager-inject") return;

  if (event.data.type === "INCOME_STATUS_RESULT") {
    const incomeStatus = event.data.payload;
    chrome.storage.local.set(
      {
        workmanager_incomeStatus: {
          data: incomeStatus,
          updatedAt: new Date().toISOString(),
        },
      },
      () => {
        const total = Object.keys(incomeStatus).length;
        const processed = Object.values(incomeStatus).filter(
          (v) => v.건수 !== null && v.건수 > 0
        ).length;
        console.log(
          `[WorkManager] 수입결의 조회 결과 저장 완료: 전체 ${total}건 중 처리됨 ${processed}건`
        );
      }
    );
  }

  if (event.data.type === "FUND_STATUS_RESULT") {
    const fundStatus = event.data.payload;
    chrome.storage.local.set(
      {
        workmanager_fundStatus: {
          data: fundStatus,
          updatedAt: new Date().toISOString(),
        },
      },
      () => {
        const total = Object.keys(fundStatus).length;
        const needsAction = Object.values(fundStatus).filter(
          (v) => !v.조회실패 && v.입금잔액 > 0
        ).length;
        console.log(
          `[WorkManager] 자금현황 조회 결과 저장 완료: 전체 ${total}건 중 수입결의 필요 ${needsAction}건`
        );
      }
    );
  }

  if (event.data.type === "PROJECT_TYPE_RESULT") {
    const projectType = event.data.payload;
    chrome.storage.local.set(
      {
        workmanager_projectType: {
          data: projectType,
          updatedAt: new Date().toISOString(),
        },
      },
      () => {
        const total = Object.keys(projectType).length;
        console.log(`[WorkManager] 과제구분 조회 결과 저장 완료: 전체 ${total}건`);
      }
    );
  }
});