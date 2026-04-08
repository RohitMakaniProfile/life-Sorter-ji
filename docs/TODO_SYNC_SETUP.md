# TODO Sync Setup: GitHub Gist ↔ Google Sheets

## Overview
1. Store TODO.md as a GitHub Gist
2. Google Apps Script syncs bidirectionally
3. Update status in Sheets → auto-updates Gist

---

## Step 1: Create GitHub Gist

1. Go to https://gist.github.com
2. Create new gist with filename `TODO.md`
3. Copy content from `docs/TODO.md`
4. Save and copy the Gist ID from URL (e.g., `https://gist.github.com/username/GIST_ID`)

---

## Step 2: Create GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. Generate new token (classic) with `gist` scope
3. Save the token securely

---

## Step 3: Google Apps Script

1. Create new Google Sheet
2. Extensions → Apps Script
3. Paste this code:

```javascript
const GIST_ID = 'YOUR_GIST_ID';
const GITHUB_TOKEN = 'YOUR_GITHUB_TOKEN';
const GIST_FILENAME = 'TODO.md';
const SHEET_NAME = 'Dev Tasks';  // ← Change this to your existing sheet name

// Column indices (0-based) matching your sheet: Date | Task | Rep | Remark | (empty)
const COL_DATE = 0;
const COL_TASK = 1;
const COL_REP = 2;
const COL_REMARK = 3;
const COL_SOURCE = 4;  // We'll use the empty column for Source tracking

// Fetch TODO from Gist and populate Sheet
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
    
    // Debug: show available files
    const availableFiles = Object.keys(gist.files || {});
    Logger.log('Available files in gist: ' + availableFiles.join(', '));
    
    if (!gist.files || !gist.files[GIST_FILENAME]) {
      throw new Error(`File "${GIST_FILENAME}" not found in gist. Available files: ${availableFiles.join(', ')}`);
    }
    
    const content = gist.files[GIST_FILENAME].content;
    const tasksByAssignee = parseTodoMarkdown(content);
    populateSheet(tasksByAssignee);
    
    SpreadsheetApp.getUi().alert('✅ Sync complete! Pulled ' + Object.keys(tasksByAssignee).length + ' assignees from Gist.');
  } catch (e) {
    SpreadsheetApp.getUi().alert('❌ Sync failed:\n\n' + e.message + '\n\nCheck:\n1. GIST_ID is correct\n2. GITHUB_TOKEN has gist scope\n3. GIST_FILENAME matches exactly');
    Logger.log('syncFromGist error: ' + e.message);
  }
}

// Parse TODO.md into structured data grouped by assignee
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
    
    // Match task lines - more flexible pattern
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

// Populate sheet matching your format: Date | Task | Rep | Remark | Source
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
    // Skip empty rows and TODO.md sourced rows
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
    // Rep column validation: Harsh, Rohit
    const repRule = SpreadsheetApp.newDataValidation()
      .requireValueInList(['Harsh', 'Rohit'], true)
      .build();
    sheet.getRange(2, COL_REP + 1, dataRows, 1).setDataValidation(repRule);
    
    // Remark column validation: Done, In Progress, TODO
    const remarkRule = SpreadsheetApp.newDataValidation()
      .requireValueInList(['Done', 'In Progress', 'TODO'], true)
      .build();
    sheet.getRange(2, COL_REMARK + 1, dataRows, 1).setDataValidation(remarkRule);
  }
}

// Sync changes from Sheet back to Gist (only TODO.md sourced rows)
function syncToGist() {
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
}

// Set up triggers
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
  
  // Sync to Gist on edit (with delay to batch edits)
  ScriptApp.newTrigger('syncToGist')
    .forSpreadsheet(SpreadsheetApp.getActive())
    .onEdit()
    .create();
}

// Manual sync buttons (add to menu)
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('TODO Sync')
    .addItem('↓ Pull from Gist', 'syncFromGist')
    .addItem('↑ Push to Gist', 'syncToGist')
    .addItem('⚙️ Setup Auto-Sync', 'setupTriggers')
    .addToUi();
}
```

4. Run `setupTriggers()` once to enable auto-sync

---

## Step 4: Usage

| Action | Result |
|--------|--------|
| Edit TODO.md in Gist | Sheet updates within 1 hour (or run `syncFromGist` manually) |
| Change status in Sheet | Gist updates immediately |
| Pull Gist to local | Get latest TODO.md with updated statuses |

---

## Step 5: Sync local repo with Gist

Add to your workflow:

```bash
# Pull latest from Gist
curl -s "https://gist.githubusercontent.com/USERNAME/GIST_ID/raw/TODO.md" > docs/TODO.md

# Or add as git alias
git config alias.todo '!curl -s "https://gist.githubusercontent.com/USERNAME/GIST_ID/raw/TODO.md" > docs/TODO.md && cat docs/TODO.md'
```

Then just run: `git todo`

