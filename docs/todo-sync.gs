const GIST_ID = 'ee92556c3f1c8d6e9b3976f771245ef3';
const GITHUB_TOKEN = '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';
const GIST_FILENAME = 'DOABLE_CLAW_TODO.md';
const SHEET_NAME = 'Dev Tasks';

// Column indices (0-based) matching your sheet: Date | Task | Rep | Remark | Source
const COL_DATE = 0;
const COL_TASK = 1;
const COL_REP = 2;
const COL_REMARK = 3;
const COL_SOURCE = 4;

// ============================================
// SYNC FROM GIST → SHEET
// ============================================

function syncFromGist() {
  try {
    const response = UrlFetchApp.fetch(`https://api.github.com/gists/${GIST_ID}`, {
      headers: { 'Authorization': `token ${GITHUB_TOKEN}` },
      muteHttpExceptions: true
    });

    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode !== 200) {
      throw new Error(`GitHub API error ${responseCode}: ${responseText}`);
    }

    const gist = JSON.parse(responseText);

    const availableFiles = Object.keys(gist.files || {});
    Logger.log('Available files in gist: ' + availableFiles.join(', '));

    if (!gist.files || !gist.files[GIST_FILENAME]) {
      throw new Error(`File "${GIST_FILENAME}" not found in gist. Available files: ${availableFiles.join(', ')}`);
    }

    const content = gist.files[GIST_FILENAME].content;
    const tasksByAssignee = parseTodoMarkdown(content);
    populateSheet(tasksByAssignee);

    const totalTasks = Object.values(tasksByAssignee).reduce((sum, tasks) => sum + tasks.length, 0);
    SpreadsheetApp.getUi().alert(`✅ Sync complete!\n\nPulled ${Object.keys(tasksByAssignee).length} assignees, ${totalTasks} tasks from Gist.`);
  } catch (e) {
    SpreadsheetApp.getUi().alert('❌ Sync failed:\n\n' + e.message + '\n\nCheck:\n1. GIST_ID is correct\n2. GITHUB_TOKEN has gist scope\n3. GIST_FILENAME matches exactly');
    Logger.log('syncFromGist error: ' + e.message);
  }
}

// ============================================
// PARSE MARKDOWN
// ============================================

function parseTodoMarkdown(content) {
  const tasksByAssignee = {};
  let currentAssignee = '';

  // Normalize line endings and split
  const lines = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');

  Logger.log('Total lines to parse: ' + lines.length);

  for (const line of lines) {
    // Match assignee headers like "## Harsh (~12h)" or "## Harsh"
    const assigneeMatch = line.match(/^##\s+(\w+)/);
    if (assigneeMatch) {
      currentAssignee = assigneeMatch[1];
      Logger.log('Found assignee: ' + currentAssignee);
      if (!tasksByAssignee[currentAssignee]) {
        tasksByAssignee[currentAssignee] = [];
      }
      continue;
    }

    // Match task lines - flexible pattern
    // Matches: "- [ ] Task name" or "- [x] Task name" with optional time estimate
    const taskMatch = line.match(/^-\s*\[([ xX])\]\s*(.+)/);
    if (taskMatch && currentAssignee) {
      let status = 'TODO';
      if (taskMatch[1].toLowerCase() === 'x') status = 'Done';

      // Clean up the task title (remove trailing time estimates like "(~2h)")
      let title = taskMatch[2].trim();
      title = title.replace(/\s*\(~\d+h?\)\s*$/, '').trim();

      Logger.log('Found task for ' + currentAssignee + ': ' + title);

      tasksByAssignee[currentAssignee].push({
        title: title,
        status: status
      });
    }
  }

  Logger.log('Parsed assignees: ' + Object.keys(tasksByAssignee).join(', '));
  Logger.log('Total tasks: ' + Object.values(tasksByAssignee).reduce((sum, tasks) => sum + tasks.length, 0));

  return tasksByAssignee;
}

// ============================================
// POPULATE SHEET
// ============================================

function populateSheet(tasksByAssignee) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) {
    throw new Error(`Sheet "${SHEET_NAME}" not found.`);
  }

  const existingData = sheet.getDataRange().getValues();
  const rowsToKeep = [];

  // Helper to ensure row has exactly 5 columns
  function normalizeRow(row) {
    const normalized = [];
    for (let i = 0; i < 5; i++) {
      normalized.push(row[i] !== undefined ? row[i] : '');
    }
    return normalized;
  }

  // Keep header row
  if (existingData.length > 0) {
    rowsToKeep.push(normalizeRow(existingData[0]));
  } else {
    rowsToKeep.push(['Date', 'Task', 'Rep', 'Remark', 'Source']);
  }

  // Keep non-TODO.md rows (manual entries)
  for (let i = 1; i < existingData.length; i++) {
    const row = existingData[i];
    if (row[COL_SOURCE] === 'TODO.md') continue;
    if (row[COL_TASK] && row[COL_TASK].toString().trim()) {
      rowsToKeep.push(normalizeRow(row));
    }
  }

  // Add empty row separator before synced tasks
  if (rowsToKeep.length > 1) {
    rowsToKeep.push(['', '', '', '', '']);
  }

  // Add tasks grouped by assignee with empty row between each
  const assignees = Object.keys(tasksByAssignee);
  for (let a = 0; a < assignees.length; a++) {
    const assignee = assignees[a];
    const tasks = tasksByAssignee[assignee];

    for (const task of tasks) {
      rowsToKeep.push(['', task.title, assignee, task.status, 'TODO.md']);
    }

    // Add empty row between assignees (except after last one)
    if (a < assignees.length - 1) {
      rowsToKeep.push(['', '', '', '', '']);
    }
  }

  // Write back
  sheet.clearContents();
  if (rowsToKeep.length > 0) {
    sheet.getRange(1, 1, rowsToKeep.length, 5).setValues(rowsToKeep);
  }

  // Add data validations
  const dataRows = rowsToKeep.length - 1;
  if (dataRows > 0) {
    const repRule = SpreadsheetApp.newDataValidation()
      .requireValueInList(['Harsh', 'Rohit'], true)
      .build();
    sheet.getRange(2, COL_REP + 1, dataRows, 1).setDataValidation(repRule);

    const remarkRule = SpreadsheetApp.newDataValidation()
      .requireValueInList(['Done', 'In Progress', 'TODO'], true)
      .build();
    sheet.getRange(2, COL_REMARK + 1, dataRows, 1).setDataValidation(remarkRule);
  }
}

// ============================================
// SYNC FROM SHEET → GIST
// ============================================

function syncToGist() {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
    if (!sheet) return;

    const data = sheet.getDataRange().getValues();

    // Filter only TODO.md sourced tasks and group by assignee
    const tasksByAssignee = {};
    for (let i = 1; i < data.length; i++) {
      const row = data[i];
      const task = row[COL_TASK];
      const rep = row[COL_REP];
      const remark = row[COL_REMARK];
      const source = row[COL_SOURCE];

      if (source !== 'TODO.md') continue;
      if (!task || !rep) continue;

      if (!tasksByAssignee[rep]) tasksByAssignee[rep] = [];
      tasksByAssignee[rep].push({ title: task, status: remark });
    }

    // Generate markdown
    let markdown = `# TODO

> **Updated:** ${new Date().toISOString().split('T')[0]}

---

`;

    for (const [assignee, tasks] of Object.entries(tasksByAssignee)) {
      markdown += `## ${assignee}\n\n`;

      for (const task of tasks) {
        const checkbox = task.status === 'Done' ? 'x' : ' ';
        markdown += `- [${checkbox}] ${task.title}\n`;
      }
      markdown += '\n---\n\n';
    }

    // Update Gist
    UrlFetchApp.fetch(`https://api.github.com/gists/${GIST_ID}`, {
      method: 'PATCH',
      headers: {
        'Authorization': `token ${GITHUB_TOKEN}`,
        'Content-Type': 'application/json'
      },
      payload: JSON.stringify({ files: { [GIST_FILENAME]: { content: markdown } } })
    });

    Logger.log('Synced to Gist successfully');
  } catch (e) {
    Logger.log('syncToGist error: ' + e.message);
  }
}

// ============================================
// TRIGGERS & MENU
// ============================================

function setupTriggers() {
  // Remove existing triggers first
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    ScriptApp.deleteTrigger(trigger);
  }

  // Sync from Gist every hour
  ScriptApp.newTrigger('syncFromGist')
    .timeBased()
    .everyHours(1)
    .create();

  // Sync to Gist on edit
  ScriptApp.newTrigger('syncToGist')
    .forSpreadsheet(SpreadsheetApp.getActive())
    .onEdit()
    .create();

  SpreadsheetApp.getUi().alert('✅ Auto-sync triggers set up!\n\n• Pull from Gist: Every hour\n• Push to Gist: On edit');
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('TODO Sync')
    .addItem('↓ Pull from Gist', 'syncFromGist')
    .addItem('↑ Push to Gist', 'syncToGist')
    .addSeparator()
    .addItem('⚙️ Setup Auto-Sync', 'setupTriggers')
    .addToUi();
}

