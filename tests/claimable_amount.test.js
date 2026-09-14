const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadInjectHelpers() {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "extension", "inject.js"),
    "utf8"
  );

  function MockXMLHttpRequest() {}
  MockXMLHttpRequest.prototype.open = function () {};

  const window = {
    __WORKMANAGER_TEST__: true,
    fetch: async () => ({
      clone: () => ({ json: async () => ({}) }),
      json: async () => ({}),
    }),
    addEventListener: () => {},
    postMessage: () => {},
  };

  const context = {
    console: { log: () => {} },
    setTimeout,
    window,
    XMLHttpRequest: MockXMLHttpRequest,
  };

  vm.createContext(context);
  vm.runInContext(source, context, { filename: "extension/inject.js" });
  return context.window.__workmanagerTest;
}

test("calculates claimable amount from agreement, received supply, and received VAT", () => {
  const helpers = loadInjectHelpers();

  const result = helpers.calculateClaimableAmount({
    "INQ_AGRMT_AMT(협약액)": "60,000,000",
    "INQ_RCV_SUPPLY_AMT(입금액공급가액)": "20,000,000",
    "INQ_RCV_TAX_AMT(입금액부가세)": "2,000,000",
  });

  assert.equal(result.협약액, 60000000);
  assert.equal(result.입금액공급가액, 20000000);
  assert.equal(result.입금액부가세, 2000000);
  assert.equal(result.청구가능액, 38000000);
});

test("picks the record with agreement fields from REC responses", () => {
  const helpers = loadInjectHelpers();

  const record = helpers.pickClaimableRecord({
    REC: [
      { OTHER_AMT: "999" },
      {
        "AMT1(협약액)": "1,000",
        "AMT2(입금액공급가액)": "300",
        "AMT3(입금액부가세)": "30",
      },
    ],
  });

  const result = helpers.calculateClaimableAmount(record);
  assert.equal(result.청구가능액, 670);
});
