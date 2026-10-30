import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// phi-ui's globals.css paints every <code> with the selection colours (background + text-background).
// Inline paths and commands on these surfaces use font-courier spans instead; only code blocks
// (which reset the rule) may render <code>.
const SURFACES = [
  "src/components/computer/ComputerPanel.tsx",
  "src/components/ledger/LedgerPanel.tsx",
  "src/components/plan/PlanPanel.tsx",
  "src/components/shell/ActionMenu.tsx",
  "src/components/shell/ChatFooter.tsx",
  "src/components/shell/ChatHeader.tsx",
  "src/components/shell/MobileKeyBar.tsx",
  "src/components/shell/PhoneComposer.tsx",
  "src/components/shell/RoomList.tsx",
  "src/components/shell/RoomMenu.tsx",
  "src/components/shell/RoomRow.tsx",
  "src/components/shell/RoundIconButton.tsx",
  "src/components/shell/SettingsColumn.tsx",
  "src/components/shell/ShellColumns.tsx",
  "src/components/shell/ShellDialogs.tsx",
  "src/components/shell/SpaceBar.tsx",
  "src/components/shell/TerminalFontControls.tsx",
  "src/components/shell/WorkspaceShellContext.tsx",
  "src/components/shell/settings-nav.tsx",
  "src/components/voice/HoldToTalk.tsx",
  "src/components/voice/MicButton.tsx",
  "src/components/workspace/ChatWorkspace.tsx",
  "src/components/workspace/RulesPanel.tsx",
  "src/components/workspace/WorkspaceSheet.tsx",
  "src/pages/ConfigSettingsPages.tsx",
  "src/pages/MemorySettingsPage.tsx",
  "src/pages/WorkspaceSettingsPage.tsx",
];

describe("inline code on 0.1.16 surfaces", () => {
  it.each(SURFACES)("%s renders no bare <code>", (file) => {
    const text = readFileSync(resolve(__dirname, "../../..", file), "utf8");
    expect(text).not.toMatch(/<code[\s>]/);
  });
});
