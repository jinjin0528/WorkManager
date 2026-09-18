// content.js - isolated world (chrome.* API 사용 가능)
// 역할:
//  1) inject.js가 보낸 "과제 목록"을 내 이름으로 필터링해서 storage에 캐시
//  2) 과제 목록이 새로 캐시될 때마다, 구분(수익/목적)과 청구가능액을
//     "자동으로" 조회해서 병합함 (팝업 버튼/클릭 필요 없음)
//  3) inject.js가 보낸 "예산잔액 목록"(종료임박 팝업)도 자동 병합
//  실제 파일 다운로드는 popup에서 사용자가 버튼을 눌러야 실행됨.

// 이 스크립트는 all_frames: true로 여러 프레임(top + iframe)에 중복 로드됨.
// postMessage는 발생한 프레임 안에서만 전달되므로(다른 프레임으로 안 건너감),
// 과제 목록이 iframe에서 감지되면 그 iframe의 content.js만 이 메시지를 받게 됨.
// → 프레임 구분 없이 감지된 곳에서 바로 자동 조회를 트리거하면 됨 (중복 위험 없음)
console.log("=================================");
console.log("WorkManager Extension 시작");
console.log("현재 페이지:", location.href, window === window.top ? "(top)" : "(iframe)");
console.log("=================================");

function mergeFieldIntoProjects(projects, valueMap, fieldName) {
  return projects.map((p) => {
    const value = valueMap[p.과제번호];
    if (value === undefined || value === null) return p;
    return { ...p, [fieldName]: value };
  });
}

function mergeClaimableIntoProjects(projects, claimableMap) {
  return projects.map((p) => {
    const value = claimableMap[p.과제번호];
    if (value === undefined || value === null) return p;
    if (typeof value === "object" && !Array.isArray(value)) {
      return { ...p, ...value };
    }
    return { ...p, 청구가능액: value };
  });
}

function mergeAndSaveField(fieldName, valueMap, storageKey, label, onDone) {
  chrome.storage.local.set({ [storageKey]: valueMap }, () => {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) {
        if (onDone) onDone([]);
        return;
      }

      const merged = mergeFieldIntoProjects(cached.projects, valueMap, fieldName);
      chrome.storage.local.set(
        { workmanager_cachedProjects: { ...cached, projects: merged } },
        () => {
          console.log(`[WorkManager] ${label}을(를) 과제 목록에 병합 완료`);
          if (onDone) onDone(merged);
        }
      );
    });
  });
}

function mergeAndSaveClaimable(claimableMap, onDone) {
  chrome.storage.local.set({ workmanager_claimableMap: claimableMap }, () => {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) {
        if (onDone) onDone([]);
        return;
      }

      const merged = mergeClaimableIntoProjects(cached.projects, claimableMap);
      chrome.storage.local.set(
        {
          workmanager_cachedProjects: {
            ...cached,
            projects: merged,
            updatedAt: new Date().toISOString(),
          },
        },
        () => {
          console.log("[WorkManager] 청구가능액 계산값을 과제 목록에 병합 완료");
          if (onDone) onDone(merged);
        }
      );
    });
  });
}

function mergeIndirectCostIntoProjects(projects, indirectMap) {
  return projects.map((p) => {
    const value = indirectMap[p.과제번호];
    if (!value || value.조회실패) return p;
    return {
      ...p,
      간접비총액: value.간접비총액,
      간접비징수액: value.간접비징수액,
      간접비진행률: value.간접비진행률,
    };
  });
}

function mergeAndSaveIndirectCost(indirectMap) {
  chrome.storage.local.set({ workmanager_indirectMap: indirectMap }, () => {
    chrome.storage.local.get(["workmanager_cachedProjects"], (result) => {
      const cached = result.workmanager_cachedProjects;
      if (!cached || !cached.projects || cached.projects.length === 0) return;

      const merged = mergeIndirectCostIntoProjects(cached.projects, indirectMap);
      chrome.storage.local.set(
        { workmanager_cachedProjects: { ...cached, projects: merged, updatedAt: new Date().toISOString() } },
        () => console.log("[WorkManager] 간접비 진행률을 과제 목록에 병합 완료")
      );
    });
  });
}

// ---------------------------------------------------------------------
// 과제 목록 감지 → 캐시 갱신 → (top frame에서) 구분/청구가능액 자동 조회 시작
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

    chrome.storage.local.get(
      ["workmanager_cachedProjects", "workmanager_budgetMap", "workmanager_claimableMap"],
      (result) => {
        const cached = result.workmanager_cachedProjects;
        const cachedCount = cached ? cached.projects.length : -1;

        if (myProjects.length <= cachedCount) {
          console.log(`[WorkManager] 기존 캐시(${cachedCount}건)보다 적거나 같아 무시함`);
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

        // 이미 확보된 예산잔액 / 청구가능액(계산) / 구분 데이터가 있으면 바로 병합
        const budgetMap = result.workmanager_budgetMap || {};
        const claimableMap = result.workmanager_claimableMap || {};
        simplified = mergeFieldIntoProjects(simplified, budgetMap, "예산잔액");
        simplified = mergeClaimableIntoProjects(simplified, claimableMap);

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

            // 감지된 프레임에서 자동 조회 트리거.
            // 구분/청구가능액을 동시에 쏘면 서버 세션 쪽에서 충돌(경쟁 상태)이
            // 날 수 있어서, 구분 조회가 다 끝난 뒤 청구가능액을 이어서 실행함
            // (PROJECT_TYPE_RESULT 핸들러에서 이어서 트리거함)
            console.log("[WorkManager] 과제구분 자동 조회 시작...");
            window.postMessage(
              { source: "workmanager-content", type: "FETCH_PROJECT_TYPE", payload: simplified },
              "*"
            );
          }
        );
      }
    );
  });
});

// ---------------------------------------------------------------------
// 예산잔액 목록 감지 (종료임박 과제 안내 팝업, rmain_0005_01_r001)
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
// 수입결의 상태 조회 - 필요시 popup에서 수동 트리거 (분량이 커서 자동화는 보류)
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
});

// inject.js가 조회를 마치고 돌려준 결과를 저장
window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (!event.data || event.data.source !== "workmanager-inject") return;

  if (event.data.type === "INCOME_STATUS_RESULT") {
    const incomeStatus = event.data.payload;
    chrome.storage.local.set(
      { workmanager_incomeStatus: { data: incomeStatus, updatedAt: new Date().toISOString() } },
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
    const projectTypeMap = event.data.payload; // { prjNo: { 구분, 계정단위명 } }
    const simpleMap = {};
    Object.entries(projectTypeMap).forEach(([prjNo, entry]) => {
      if (entry && !entry.조회실패) simpleMap[prjNo] = entry.구분;
    });

    const total = Object.keys(projectTypeMap).length;
    console.log(`[WorkManager] 과제구분 조회 결과: 전체 ${total}건`);

    // 원본 상세 데이터도 보관 (필요시 참고용)
    chrome.storage.local.set({
      workmanager_projectType: { data: projectTypeMap, updatedAt: new Date().toISOString() },
    });

    // 과제 목록에 "구분" 필드로 바로 병합 (별도 파일 없이 myProjects.json에 포함됨)
    // → 병합이 끝난 뒤에야 청구가능액 조회를 이어서 시작 (동시 실행 시 서버 세션
    //   충돌로 청구가능액 조회가 통째로 실패하는 문제가 있었음)
    mergeAndSaveField("구분", simpleMap, "workmanager_projectTypeMap", "과제구분", (merged) => {
      if (!merged || merged.length === 0) return;
      console.log("[WorkManager] 청구가능액 자동 조회 시작...");
      window.postMessage(
        { source: "workmanager-content", type: "FETCH_CLAIMABLE_AMOUNT", payload: merged },
        "*"
      );
    });
  }

  if (event.data.type === "CLAIMABLE_RESULT") {
    const claimableMap = event.data.payload;
    const total = Object.keys(claimableMap).length;
    const success = Object.values(claimableMap).filter(
      (v) => v !== null && (typeof v !== "object" || v.청구가능액 !== undefined)
    ).length;
    console.log(`[WorkManager] 청구가능액 조회 결과: 전체 ${total}건 중 ${success}건 성공`);

    // 청구가능액 병합이 끝난 뒤에야 간접비 조회를 이어서 시작 (동시 실행 시
    // 서버 세션 충돌 위험이 있어서 계속 순차적으로 체이닝함)
    mergeAndSaveClaimable(claimableMap, (merged) => {
      if (!merged || merged.length === 0) return;
      console.log("[WorkManager] 간접비 진행률 자동 조회 시작...");
      window.postMessage(
        { source: "workmanager-content", type: "FETCH_INDIRECT_COST", payload: merged },
        "*"
      );
    });
  }

  if (event.data.type === "INDIRECT_COST_RESULT") {
    const indirectMap = event.data.payload;
    const total = Object.keys(indirectMap).length;
    const success = Object.values(indirectMap).filter((v) => !v.조회실패).length;
    console.log(`[WorkManager] 간접비 진행률 조회 결과: 전체 ${total}건 중 ${success}건 성공`);
    mergeAndSaveIndirectCost(indirectMap);
  }
});