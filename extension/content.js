// content.js - isolated world (chrome.* API 사용 가능)
// 역할:
//  1) inject.js가 보낸 "과제 목록"을 내 이름으로 필터링해서 storage에 캐시
//  2) inject.js가 보낸 "예산잔액 목록"(종료임박 팝업)을 내 이름으로 필터링해서 병합
//  3) "청구가능액 조회" 능동 실행 결과를 캐시된 과제 목록의 청구가능액 필드에 병합
//  실제 파일 다운로드는 popup에서 사용자가 버튼을 눌러야 실행됨.

console.log("=================================");
console.log("WorkManager Extension 시작");
console.log("현재 페이지:", location.href);
console.log("=================================");

function mergeFieldIntoProjects(projects, valueMap, fieldName) {
  return projects.map((p) => {
    const value = valueMap[p.과제번호];
    if (value === undefined || value === null) return p;
    return { ...p, [fieldName]: value };
  });
}

function mergeAndSaveField(fieldName, valueMap, storageKey, label) {
  chrome.storage.local.set({ [storageKey]: valueMap }, () => {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) {
        console.log(`[WorkManager] ${label} 저장됨. 과제 목록 감지되면 자동 병합됩니다.`);
        return;
      }

      const merged = mergeFieldIntoProjects(cached.projects, valueMap, fieldName);
      chrome.storage.local.set(
        {
          workmanager_cachedProjects: {
            ...cached,
            projects: merged,
          },
        },
        () => {
          console.log(`[WorkManager] ${label}을(를) 과제 목록에 병합 완료`);
        }
      );
    });
  });
}

// ---------------------------------------------------------------------
// 과제 목록 감지
// ---------------------------------------------------------------------
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
    chrome.storage.local.get(
      ["workmanager_cachedProjects", "workmanager_budgetMap", "workmanager_claimableMap"],
      (result) => {
        const cached = result.workmanager_cachedProjects;
        const cachedCount = cached ? cached.projects.length : -1;

        if (myProjects.length <= cachedCount) {
          console.log(
            `[WorkManager] 기존 캐시(${cachedCount}건)보다 적거나 같아 무시함`
          );
          return;
        }

        let simplified = myProjects.map((p) => ({
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

        // 이미 확보된 예산잔액 / 청구가능액(계산) 데이터가 있으면 바로 병합
        const budgetMap = result.workmanager_budgetMap || {};
        const claimableMap = result.workmanager_claimableMap || {};
        simplified = mergeFieldIntoProjects(simplified, budgetMap, "예산잔액");
        simplified = mergeFieldIntoProjects(simplified, claimableMap, "청구가능액");

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
      }
    );
  });
});

// ---------------------------------------------------------------------
// 예산잔액 목록 감지 (종료임박 과제 안내 팝업, rmain_0005_01_r001)
// - 이 목록은 "종료 임박 과제"만 한정적으로 보여주므로, 여기 없는 과제는
//   병합되지 않고 그대로 남음 (참고용 보조 데이터)
// ---------------------------------------------------------------------
window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (!event.data || event.data.source !== "workmanager-inject") return;
  if (event.data.type !== "BUDGET_LIST_DATA") return;

  const data = event.data.payload;

  chrome.storage.local.get(["workmanager_userName"], (nameResult) => {
    const myName = nameResult.workmanager_userName;
    if (!myName) return;

    const myBudgets = data.REC.filter((p) => p.PRJ_CHRG_GRP_NM === myName);
    console.log(`[WorkManager] "${myName}" 담당 예산잔액 ${myBudgets.length}건 감지됨`);

    const budgetMap = {};
    myBudgets.forEach((p) => {
      budgetMap[p.PRJ_NO] = Number(p.BGT_BAL_AMT || 0);
    });

    mergeAndSaveField("예산잔액", budgetMap, "workmanager_budgetMap", "예산잔액");
  });
});

// -------------------------------------------------------------------
// 수입결의 상태 / 과제구분 / 청구가능액 조회 - popup에서 요청 오면,
// 캐시된 과제 목록을 inject.js(MAIN world)로 넘겨서 백그라운드 조회 시작
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
        { source: "workmanager-content", type: "FETCH_INCOME_STATUS", payload: cached.projects },
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
        { source: "workmanager-content", type: "FETCH_PROJECT_TYPE", payload: cached.projects },
        "*"
      );
    });
    sendResponse({ started: true });
    return true;
  }

  if (message.type === "START_CLAIMABLE_CHECK") {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) {
        console.log("[WorkManager] 조회할 과제 목록이 없습니다. 먼저 과제 목록을 감지해주세요.");
        return;
      }
      console.log(`[WorkManager] 청구가능액 조회 요청 전달 (${cached.projects.length}건)`);
      window.postMessage(
        { source: "workmanager-content", type: "FETCH_CLAIMABLE_AMOUNT", payload: cached.projects },
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

  if (event.data.type === "CLAIMABLE_RESULT") {
    const claimableMap = event.data.payload;
    const total = Object.keys(claimableMap).length;
    const success = Object.values(claimableMap).filter((v) => v !== null).length;
    console.log(`[WorkManager] 청구가능액 조회 결과: 전체 ${total}건 중 ${success}건 성공`);
    mergeAndSaveField("청구가능액", claimableMap, "workmanager_claimableMap", "청구가능액");
  }
});