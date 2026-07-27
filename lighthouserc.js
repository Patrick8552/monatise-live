module.exports = {
  ci: {
    collect: { staticDistDir: "./app", url: ["http://localhost/index.html"], numberOfRuns: 1 },
    assert: {
      assertions: {
        "categories:accessibility": ["error", { minScore: 0.9 }],
        "categories:best-practices": ["warn", { minScore: 0.85 }],
        "categories:performance": ["warn", { minScore: 0.7 }]
      }
    },
    upload: { target: "filesystem", outputDir: "./artifacts/lighthouse" }
  }
};
