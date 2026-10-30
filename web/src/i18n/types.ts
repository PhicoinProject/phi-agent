export type Locale =
  | "en"
  | "zh"
  | "zh-hant"
  | "ja"
  | "de"
  | "es"
  | "fr"
  | "tr"
  | "uk"
  | "af"
  | "ko"
  | "it"
  | "ga"
  | "pt"
  | "ru"
  | "hu"
  | "ar";

/** Workspace shell (spaces, rooms, Settings → Workspace). `{name}`-style placeholders. */
export interface ShellStrings {
  home: string;
  spaces: string;
  collapse: string;
  expand: string;
  running: string;
  settings: string;
  backToRooms: string;
  createSpace: string;
  createSubSpace: string;
  spaceName: string;
  parentSpace: string;
  topLevel: string;
  roomName: string;
  create: string;
  cancel: string;
  save: string;
  rename: string;
  renameTitle: string;
  searchRooms: string;
  newChat: string;
  addExistingRoom: string;
  newSubSpace: string;
  deleteSpace: string;
  deleteSpaceTitle: string;
  deleteSpaceBody: string;
  deleteSpaceDone: string;
  deleteSpaceFailed: string;
  spaceMenu: string;
  addMenu: string;
  filterAll: string;
  filterUnread: string;
  filterRunning: string;
  noRooms: string;
  agentDm: string;
  roomMenu: string;
  moveToSpace: string;
  addToSpace: string;
  copyPath: string;
  openInFiles: string;
  pathCopied: string;
  roomSettings: string;
  roomSettingsSoon: string;
  archive: string;
  moveFailed: string;
  spaceDropCycle: string;
  /** {depth}: the nesting limit, counting the room. */
  spaceDropDepth: string;
  loadFailed: string;
  openSpaces: string;
  closeSpaces: string;
  copyDirectory: string;
  openFolder: string;
  markAllRead: string;
  markAllReadFailed: string;
  plan: string;
  computer: string;
  ledger: string;
  rules: string;
  chatActions: string;
  newChatFailed: string;
  fontSmaller: string;
  fontLarger: string;
  keyBar: string;
  keyCtrl: string;
  send: string;
  micSlot: string;
  sendEnter: string;
  keyEsc: string;
  keyUp: string;
  keyDown: string;
  roomSheet: string;
  addPhotoOrFile: string;
  model: string;
  uploadFailed: string;
  resizeColumn: string;
  navWorkspace: string;
  navMemory: string;
  navAgents: string;
  navVoice: string;
  navShortcuts: string;
  navComputer: string;
  wsTitle: string;
  wsRoot: string;
  wsChange: string;
  wsChangeTitle: string;
  wsChangeBody: string;
  wsDepth: string;
  wsDepthHint: string;
  wsFence: string;
  wsFenceApprove: string;
  wsFenceStrict: string;
  wsFenceOff: string;
  wsMappings: string;
  wsCheck: string;
  wsChecking: string;
  wsNoIssues: string;
  wsMissingDir: string;
  wsUnmappedDir: string;
  saved: string;
  saveFailed: string;
  // Settings → Memory
  memTitle: string;
  memSearch: string;
  memSearchButton: string;
  memHard: string;
  memHardHint: string;
  memSoft: string;
  memSoftHint: string;
  memSoftCount: string;
  memTargetMemory: string;
  memTargetUser: string;
  memPin: string;
  memUnpin: string;
  memEdit: string;
  memEditLabel: string;
  memDemote: string;
  memPromote: string;
  memScore: string;
  memNoHard: string;
  memNoSoft: string;
  memNoMatches: string;
  memUsedToday: string;
  memUsedDaysAgo: string;
  memNeverUsed: string;
  memActionFailed: string;
  memLoadFailed: string;
}

/** Chat workspace panels (voice, Computer, Plan, Ledger, Rules) and the config settings pages. */
export interface PanelStrings {
  needsComputer: string;
  open: string;
  dismiss: string;
  close: string;
  connecting: string;
  planProgress: string;
  planEmpty: string;
  planWave: string;
  planCriticalPath: string;
  planSelf: string;
  planAgent: string;
  planStatusDone: string;
  planStatusRun: string;
  planStatusWait: string;
  ledgerSearch: string;
  ledgerAllKinds: string;
  ledgerKindDecision: string;
  ledgerKindFact: string;
  ledgerKindResult: string;
  ledgerKindBlocker: string;
  ledgerKindTodo: string;
  ledgerKindNote: string;
  ledgerKindStep: string;
  ledgerEmpty: string;
  ledgerReplacedBy: string;
  ledgerLoadFailed: string;
  rulesHint: string;
  rulesCounter: string;
  rulesLoadFailed: string;
  archived: string;
  archiveFailed: string;
  agentsTitle: string;
  agentsMaxChildren: string;
  agentsMaxChildrenHint: string;
  agentsModel: string;
  agentsModelHint: string;
  voiceTitle: string;
  voiceShortcut: string;
  voiceShortcutHint: string;
  voiceShortcutsLink: string;
  shortcutsTitle: string;
  shortcutsEscNote: string;
  voiceProvider: string;
  voiceProviderAuto: string;
  voiceAutoSend: string;
  voiceAutoSendHint: string;
  voiceReleaseFill: string;
  voiceReleaseFillHint: string;
  computerTitle: string;
  computerGeometry: string;
  computerIdle: string;
  computerIdleNever: string;
  computerIdleMinutes: string;
  configLoadFailed: string;
}

export interface Translations {
  // ── Common ──
  common: {
    save: string;
    saving: string;
    cancel: string;
    close: string;
    confirm: string;
    delete: string;
    refresh: string;
    retry: string;
    /** Optional — English fallback until translated. "{what}" = the noun that failed to load. */
    loadFailed?: string;
    loadFailedDetails?: string;
    search: string;
    loading: string;
    create: string;
    creating: string;
    set: string;
    replace: string;
    clear: string;
    live: string;
    off: string;
    enabled: string;
    disabled: string;
    active: string;
    inactive: string;
    unknown: string;
    untitled: string;
    none: string;
    form: string;
    noResults: string;
    of: string;
    page: string;
    msgs: string;
    tools: string;
    match: string;
    other: string;
    configured: string;
    removed: string;
    failedToToggle: string;
    failedToRemove: string;
    failedToReveal: string;
    collapse: string;
    expand: string;
    general: string;
    messaging: string;
    // Optional: non-English locales fall back to the English literal in the
    // component until translated, matching the enriched-profiles keys.
    gateway?: string;
    gatewayHint?: string;
    pluginLoadFailed: string;
    pluginNotRegistered: string;
  };

  // ── App shell ──
  app: {
    brand: string;
    brandShort: string;
    closeNavigation: string;
    closeModelTools: string;
    footer: {
      org: string;
    };
    activeSessionsLabel: string;
    gatewayStatusLabel: string;
    gatewayStrip: {
      degraded?: string;
      failed: string;
      heartbeatStale?: string;
      off: string;
      running: string;
      starting: string;
      stopped: string;
    };
    nav: {
      analytics: string;
      chat: string;
      config: string;
      cron: string;
      documentation: string;
      keys: string;
      logs: string;
      models: string;
      profiles: string;
      plugins: string;
      sessions: string;
      skills: string;
    };
    modelToolsSheetSubtitle: string;
    modelToolsSheetTitle: string;
    navigation: string;
    openDocumentation: string;
    openNavigation: string;
    pluginNavSection: string;
    sessionsActiveCount: string;
    statusOverview: string;
    system: string;
    webUi: string;
    /** Optional — fall back to English literals until translated. */
    managingProfile?: string;
    currentProfileOption?: string;
    managingProfileBanner?: string;
    /** NS-656 memory-pressure banner — optional, English fallback. */
    memoryOomRestartBanner?: string;
    memoryCriticalBanner?: string;
    memoryElevatedBanner?: string;
    /** NS-656 disk-usage banner — optional, English fallback. */
    diskCriticalBanner?: string;
    diskElevatedBanner?: string;
    /** Multi-profile host whose gateway boots standalone on a guard — optional, English fallback. */
    multiplexStandaloneBanner?: string;
    dismiss?: string;
    /** First-run shared-metrics offer — optional, English fallback. */
  };

  // ── Status page ──
  status: {
    actionFailed: string;
    actionFinished: string;
    actionFinishedOwed: string;
    actions: string;
    agent: string;
    connected: string;
    connectedPlatforms: string;
    disabled?: string;
    disconnected: string;
    error: string;
    failed: string;
    gateway: string;
    gatewayFailedToStart: string;
    lastUpdate: string;
    noneRunning: string;
    notRunning: string;
    pid: string;
    platformDisconnected: string;
    platformError: string;
    activeSessions: string;
    recentSessions: string;
    restartGateway: string;
    restartGatewayConfirmMessage?: string;
    restartGatewayConfirmTitle?: string;
    restartingGateway: string;
    running: string;
    runningRemote: string;
    startFailed: string;
    starting: string;
    startedInBackground: string;
    stopped: string;
    updatePhi: string;
    updatePhiConfirmMessage?: string;
    updatePhiConfirmNow?: string;
    updatePhiConfirmTitle?: string;
    updatingPhi: string;
    waitingForOutput: string;
  };

  // ── Sessions page ──
  sessions: {
    title: string;
    history: string;
    overview: string;
    filterChats: string;
    filterAutomation: string;
    filterAll: string;
    sourceFilter: string;
    anySource: string;
    searchPlaceholder: string;
    noSessions: string;
    noSessionsInFilter: string;
    noMatch: string;
    startConversation: string;
    noMessages: string;
    untitledSession: string;
    deleteSession: string;
    confirmDeleteTitle: string;
    confirmDeleteMessage: string;
    sessionDeleted: string;
    failedToDelete: string;
    deleteEmpty: string;
    deleteEmptyConfirmTitle: string;
    deleteEmptyConfirmMessage: string;
    emptySessionsDeleted: string;
    failedToDeleteEmpty: string;
    selectSession: string;
    selectAllOnPage: string;
    clearSelection: string;
    selectedCount: string;
    deleteSelected: string;
    deleteSelectedConfirmTitle: string;
    deleteSelectedConfirmMessage: string;
    selectedSessionsDeleted: string;
    selectedSessionsSkippedActive: string;
    failedToDeleteSelected: string;
    resumeInChat: string;
    newChat: string;
    workspace: string;
    workspaceDefault: string;
    workspaceRescan: string;
    workspaceCustom: string;
    previousPage: string;
    nextPage: string;
    roles: {
      user: string;
      assistant: string;
      system: string;
      tool: string;
    };
  };

  // ── Analytics page ──
  analytics: {
    period: string;
    totalTokens: string;
    totalSessions: string;
    apiCalls: string;
    dailyTokenUsage: string;
    dailyBreakdown: string;
    perModelBreakdown: string;
    topSkills: string;
    skill: string;
    loads: string;
    edits: string;
    lastUsed: string;
    input: string;
    output: string;
    total: string;
    noUsageData: string;
    startSession: string;
    date: string;
    model: string;
    tokens: string;
    perDayAvg: string;
    acrossModels: string;
    inOut: string;
  };

  // ── Models page ──
  models: {
    modelsUsed: string;
    estimatedCost: string;
    tokens: string;
    sessions: string;
    avgPerSession: string;
    apiCalls: string;
    toolCalls: string;
    noModelsData: string;
    startSession: string;
  };

  // ── Logs page ──
  logs: {
    title: string;
    autoRefresh: string;
    file: string;
    level: string;
    component: string;
    lines: string;
    noLogLines: string;
  };

  // ── Cron page ──
  cron: {
    /** Optional — English fallback until translated. */
    loadWhat?: string;
    scriptRequired?: string;
    confirmDeleteMessage: string;
    confirmDeleteTitle: string;
    newJob: string;
    nameOptional: string;
    namePlaceholder: string;
    prompt: string;
    promptPlaceholder: string;
    schedule: string;
    schedulePlaceholder: string;
    scheduleMode: string;
    scheduleModes: {
      interval: string;
      daily: string;
      weekly: string;
      monthly: string;
      once: string;
      custom: string;
      intervalEvery: string;
      intervalUnit: string;
      unitMinutes: string;
      unitHours: string;
      unitDays: string;
      timeOfDay: string;
      weekdays: string;
      weekdaysShort: [string, string, string, string, string, string, string];
      dayOfMonth: string;
      onceAt: string;
      customLabel: string;
      customPlaceholder: string;
      customHint: string;
      preview: string;
      previewEmpty: string;
    };
    scheduleDescribe: {
      none: string;
      everyMinutes: string;
      everyHours: string;
      everyDays: string;
      dailyAt: string;
      weeklyAt: string;
      monthlyAt: string;
      onceAt: string;
    };
    deliverTo: string;
    scheduledJobs: string;
    noJobs: string;
    last: string;
    next: string;
    overdueSince?: string;
    schedulerLastTicked?: string;
    pause: string;
    resume: string;
    triggerNow: string;
    delivery: {
      local: string;
      telegram: string;
      discord: string;
      slack: string;
      email: string;
      needsHomeChannel?: string;
      noneConfigured?: string;
    };
  };

  // ── Plugins page ──
  pluginsPage: {
    contextEngineLabel: string;
    dashboardSlots: string;
    disableRuntime: string;
    enableAfterInstall: string;
    enableRuntime: string;
    toggleTakesEffectAfterRestart: string;
    forceReinstall: string;
    headline: string;
    identifierLabel: string;
    inactive: string;
    installBtn: string;
    installHeading: string;
    installHint: string;
    memoryProviderLabel: string;
    missingEnvWarn: string;
    noDashboardTab: string;
    openTab: string;
    orphanHeading: string;
    pluginListHeading: string;
    providerDefaults: string;
    providersHeading: string;
    providersHint: string;
    refreshDashboard: string;
    removeConfirm: string;
    removeHint: string;
    rescanHeading: string;
    rescanHint: string;
    runtimeHeading: string;
    saveProviders: string;
    savedProviders: string;
    sourceBadge: string;
    authRequired: string;
    authRequiredHint: string;
    updateGit: string;
    /** Optional: locales without it fall back to the English body at the call site. */
    updateConsentBody?: (name: string, sha: string) => string;
    /** Optional, English fallback: the scan rated an update caution; confirming retries with force. */
    updateScanBody?: (name: string, count: number) => string;
    /** Optional, English fallback: the scan rated an update dangerous; never overridable. */
    updateScanBlocked?: (name: string) => string;
    versionBadge: string;
    showInSidebar: string;
    hideFromSidebar: string;
    // Catalog section (en-only fallback convention — optional keys).
    catalogHeading?: string;
    catalogHint?: string;
    catalogSearchPlaceholder?: string;
    catalogEmpty?: string;
    catalogEmptyDocsLink?: string;
    catalogInstallBtn?: string;
    catalogInstalledBadge?: string;
    catalogUpdateBtn?: string;
    catalogRemovedBadge?: string;
    catalogConfirmTitle?: string;
    catalogConfirmInstallNote?: string;
    catalogRequiresEnv?: string;
    removedFromCatalog?: string;
  };

  // ── Profiles page ──
  profiles: {
    newProfile: string;
    name: string;
    namePlaceholder: string;
    nameRequired: string;
    nameRule: string;
    invalidName: string;
    cloneFrom: string;
    cloneFromNone: string;
    allProfiles: string;
    noProfiles: string;
    defaultBadge: string;
    hasEnv: string;
    model: string;
    skills: string;
    rename: string;
    editSoul: string;
    soulSection: string;
    soulPlaceholder: string;
    saveSoul: string;
    soulSaved: string;
    openInTerminal: string;
    commandCopied: string;
    copyFailed: string;
    confirmDeleteTitle: string;
    confirmDeleteMessage: string;
    created: string;
    deleted: string;
    renamed: string;
    // Optional keys added for the enriched profiles experience. Non-English
    // locales fall back to the English literal in the component until
    // translated, so these are optional to avoid churning every locale file.
    activeProfile?: string;
    activeBadge?: string;
    setActive?: string;
    activeSet?: string;
    gatewayRunning?: string;
    gatewayStopped?: string;
    gatewayRunningWarning?: string;
    aliasBadge?: string;
    description?: string;
    descriptionPlaceholder?: string;
    noDescription?: string;
    editDescription?: string;
    descriptionSaved?: string;
    reviewBadge?: string;
    autoGenerate?: string;
    generating?: string;
    describeFailed?: string;
    distribution?: string;
    advancedOptions?: string;
    cloneAll?: string;
    noSkillsOption?: string;
    descriptionOptional?: string;
    modelOptional?: string;
    modelInherit?: string;
    modelLoading?: string;
    modelNone?: string;
    editModel?: string;
    modelSaved?: string;
    modelSelect?: string;
    actions?: string;
    manageSkills?: string;
    activeSetHint?: string;
  };

  // ── Skills page ──
  skills: {
    title: string;
    searchPlaceholder: string;
    /** Optional — English fallback until translated. */
    loadWhat?: string;
    browseHub?: string;
    createSkill?: string;
    enabledOf: string;
    all: string;
    categories: string;
    filters: string;
    noSkills: string;
    noSkillsMatch: string;
    skillCount: string;
    resultCount: string;
    noDescription: string;
    toolsets: string;
    toolsetLabel: string;
    noToolsetsMatch: string;
    setupNeeded: string;
    disabledForCli: string;
    more: string;
    /** Optional — fall back to English literals until translated. */
    profileSelector?: string;
    currentProfile?: string;
    managingProfile?: string;
  };

  // ── Config page ──
  config: {
    configPath: string;
    filters: string;
    sections: string;
    exportConfig: string;
    importConfig: string;
    resetDefaults: string;
    resetScopeTooltip: string;
    confirmResetScope: string;
    resetScopeToast: string;
    rawYaml: string;
    searchResults: string;
    fields: string;
    noFieldsMatch: string;
    configSaved: string;
    yamlConfigSaved: string;
    failedToSave: string;
    failedToSaveYaml: string;
    failedToLoadRaw: string;
    configImported: string;
    invalidJson: string;
    categories: {
      general: string;
      agent: string;
      terminal: string;
      display: string;
      delegation: string;
      memory: string;
      compression: string;
      security: string;
      browser: string;
      voice: string;
      tts: string;
      stt: string;
      logging: string;
      discord: string;
      auxiliary: string;
    };
  };

  // ── Env / Keys page ──
  env: {
    changesNote: string;
    confirmClearMessage: string;
    confirmClearTitle: string;
    description: string;
    enterValue: string;
    getKey: string;
    hideAdvanced: string;
    hideValue: string;
    keysCount: string;
    llmProviders: string;
    notConfigured: string;
    notSet: string;
    providersConfigured: string;
    replaceCurrentValue: string;
    showAdvanced: string;
    showLess: string;
    showMore: string;
    showValue: string;
    customTitle: string;
    customHint: string;
    customConfigured: string;
    addCustomKey: string;
    customKeyName: string;
    customKeyNamePlaceholder: string;
    add: string;
    invalidKeyName: string;
  };

  // ── OAuth ──
  oauth: {
    title: string;
    providerLogins: string;
    description: string;
    connected: string;
    expired: string;
    notConnected: string;
    runInTerminal: string;
    noProviders: string;
    login: string;
    disconnect: string;
    managedExternally: string;
    copied: string;
    copyCode: string;
    copyFailed: string;
    cli: string;
    copyCliCommand: string;
    connect: string;
    sessionExpires: string;
    sessionExpiredNoError: string;
    initiatingLogin: string;
    exchangingCode: string;
    connectedClosing: string;
    loginFailed: string;
    sessionExpired: string;
    reOpenAuth: string;
    reOpenVerification: string;
    submitCode: string;
    pasteCode: string;
    waitingAuth: string;
    enterCodePrompt: string;
    pkceStep1: string;
    pkceStep2: string;
    pkceStep3: string;
    flowLabels: {
      pkce: string;
      device_code: string;
      external: string;
    };
    expiresIn: string;
  };

  // ── Language switcher ──
  language: {
    switchTo: string;
  };

  // ── Theme switcher ──
  theme: {
    title: string;
    switchTheme: string;
    /** Font-override section (optional — locales fall back to English). */
    fontTitle?: string;
    fontDefault?: string;
    fontDefaultHint?: string;
    fontSans?: string;
    fontSerif?: string;
    fontMono?: string;
  };

  // ── Achievements plugin (plugins/phi-achievements) ──
  achievements: {
    hero: {
      kicker: string;
      title: string;
      subtitle: string;
      scan_subtitle: string;
    };
    actions: {
      rescan: string;
    };
    stats: {
      unlocked: string;
      unlocked_hint: string;
      discovered: string;
      discovered_hint: string;
      secrets: string;
      secrets_hint: string;
      highest_tier: string;
      highest_tier_hint: string;
      latest: string;
      latest_hint_empty: string;
      none_yet: string;
    };
    state: {
      unlocked: string;
      discovered: string;
      secret: string;
    };
    tier: {
      target: string;
      hidden: string;
      complete: string;
      objective: string;
    };
    progress: {
      hidden: string;
    };
    scan: {
      building_headline: string;
      building_detail: string;
      starting_headline: string;
      progress_detail: string;
      idle_detail: string;
    };
    guide: {
      tiers_header: string;
      secret_header: string;
      secret_body: string;
      scan_status_header: string;
      scan_status_body: string;
      what_scanned_header: string;
      what_scanned_body: string;
    };
    card: {
      share_title: string;
      share_label: string;
      share_text: string;
      how_to_reveal: string;
      what_counts: string;
      evidence_label: string;
      evidence_session_fallback: string;
      no_evidence: string;
    };
    latest: {
      header: string;
    };
    empty: {
      no_secrets_header: string;
      no_secrets_body: string;
    };
    filters: {
      all_categories: string;
      visibility_all: string;
      visibility_unlocked: string;
      visibility_discovered: string;
      visibility_secret: string;
    };
    share: {
      dialog_label: string;
      header: string;
      close: string;
      rendering: string;
      card_alt: string;
      error_generic: string;
      x_title: string;
      x_button: string;
      copy_title: string;
      copy_button: string;
      copied: string;
      download_button: string;
      hint: string;
      clipboard_unsupported: string;
      tweet_text: string;
    };
  };

  // ── Kanban ──
  kanban: {
    loading: string;
    loadFailed: string;
    loadFailedHint: string;
    board: string;
    newBoard: string;
    newBoardTitle: string;
    newBoardDescription: string;
    slug: string;
    slugHint: string;
    displayName: string;
    displayNameHint: string;
    description: string;
    descriptionHint: string;
    icon: string;
    iconHint: string;
    switchAfterCreate: string;
    cancel: string;
    creating: string;
    createBoard: string;
    search: string;
    filterCards: string;
    tenant: string;
    allTenants: string;
    assignee: string;
    allProfiles: string;
    showArchived: string;
    lanesByProfile: string;
    nudgeDispatcher: string;
    refresh: string;
    selected: string;
    complete: string;
    archive: string;
    apply: string;
    clear: string;
    createTask: string;
    noTasks: string;
    unassigned: string;
    needsAssignee?: string;
    needsAssigneeHint?: string;
    untitled: string;
    loadingDetail: string;
    addComment: string;
    comment: string;
    status: string;
    workspace: string;
    skills: string;
    createdBy: string;
    result: string;
    comments: string;
    events: string;
    runHistory: string;
    workerLog: string;
    loadingLog: string;
    noWorkerLog: string;
    noDescription: string;
    noComments: string;
    edit: string;
    save: string;
    dependencies: string;
    parents: string;
    children: string;
    none: string;
    addParent: string;
    addChild: string;
    removeDependency: string;
    block: string;
    unblock: string;
    notifyHomeChannels: string;
    diagnostics: string;
    hide: string;
    show: string;
    attention: string;
    tasksNeedAttention: string;
    taskNeedsAttention: string;
    diagnostic: string;
    open: string;
    close: string;
    reassignTo: string;
    copied: string;
    copyCommand: string;
    reclaim: string;
    reassign: string;
    renderingError: string;
    reloadView: string;
    wsAuthFailed: string;
    markDone: string;
    markArchived: string;
    warning: string;
    phantomIds: string;
    active: string;
    ended: string;
    noProfile: string;
    showAllAttempts: string;
    sendingUpdates: string;
    sendNotifications: string;
    archiveBoardConfirm: string;
    archiveBoardTitle: string;
    boardSwitcherHint: string;
    taskCreatedWarning: string;
    moveFailed: string;
    bulkFailed: string;
    completionBlockedHallucination: string;
    suspectedHallucinatedReferences: string;
    pickProfileFirst: string;
    unblockedMessage: string;
    unblockFailed: string;
    reclaimedMessage: string;
    reclaimFailed: string;
    reassignedMessage: string;
    reassignFailed: string;
    selectForBulk: string;
    clickToEdit: string;
    clickToEditAssignee: string;
    emptyAssignee: string;
    columnLabels: {
      triage: string;
      todo: string;
      scheduled: string;
      ready: string;
      running: string;
      blocked: string;
      done: string;
      archived: string;
    };
    columnHelp: {
      triage: string;
      todo: string;
      scheduled: string;
      ready: string;
      running: string;
      blocked: string;
      done: string;
      archived: string;
    };
    confirmDone: string;
    confirmArchive: string;
    confirmBlocked: string;
    confirmScheduled?: string;
    confirmDoneMany: string;
    confirmArchiveMany: string;
    confirmBlockedMany: string;
    completionSummary: string;
    completionSummaryRequired: string;
    triagePlaceholder: string;
    taskTitlePlaceholder: string;
    specifier: string;
    assigneePlaceholder: string;
    priority: string;
    skillsPlaceholder: string;
    noParent: string;
    workspacePathDir: string;
    workspacePathOptional: string;
    logTruncated: string;
    logAt: string;
    // Optional keys added with the modal create-task dialog, board-settings
    // dialog, and comment workflow hint. Non-English locales fall back to
    // the English literal in the plugin bundle until translated, so these
    // are optional to avoid churning every locale file.
    newTaskTitle?: string;
    taskTitleLabel?: string;
    assigneeLabel?: string;
    assigneeLabelHint?: string;
    skillsLabel?: string;
    skillsLabelHint?: string;
    parentLabel?: string;
    parentLabelHint?: string;
    create?: string;
    boardSettings?: string;
    boardSettingsTitle?: string;
    boardSettingsTitleFor?: string;
    projectDirectoryOverrideHint?: string;
    saving?: string;
    commentHint?: string;
    commentHintTitle?: string;
    // Optional in-app confirm-dialog strings for the trash/delete flow;
    // non-English locales fall back to the English literals in the bundle.
    trash?: {
      confirmTitle?: string;
      confirmManyTitle?: string;
    };
  };

  // ── Rich chat rendering + file preview (optional — locales fall back to English) ──
  rich?: RichTranslations;
  // ── Workspace shell — optional; other locales fall back to English. ──
  shell?: Partial<ShellStrings>;
  // ── Chat workspace panels and config settings pages — optional; falls back to English. ──
  panels?: Partial<PanelStrings>;
  // Optional: dictation (mic / hold-to-talk) and the bot-desktop Computer panel. Other locales
  // fall back to the English strings until translated.
  voiceComputer?: {
    dictate: string;
    stopDictation: string;
    insecure: string;
    unsupported: string;
    requesting: string;
    finalizing: string;
    chooseMic: string;
    systemDefaultMic: string;
    allowMicDevices: string;
    holdToTalk: string;
    slideHint: string;
    lockedHint: string;
    computer: string;
    botDesktop: string;
    close: string;
    back: string;
    notInstalled: string;
    installWith: string;
    stopped: string;
    starting: string;
    startFailed: string;
    retry: string;
    connecting: string;
    agentDriving: string;
    otherDriving: string;
    watch: string;
    watching: string;
    takeOver: string;
    youControl: string;
    youControlShort: string;
    handBack: string;
    noteToAgent: string;
    fit: string;
    actualSize: string;
    zoomIn: string;
    zoomOut: string;
    paste: string;
    pastePrompt: string;
    pasteTooLong: string;
    pasteSent: string;
    keyboard: string;
    keyboardHint: string;
    arrowUp: string;
    arrowDown: string;
    arrowLeft: string;
    arrowRight: string;
    sidewaysHint: string;
    fullScreen: string;
    exitFullScreen: string;
    confirmTitle: string;
    confirmBody: string;
    leaseCaveat: string;
    evicted: string;
    controlTaken: string;
    streamLost: string;
    reconnect: string;
  };
}

export interface RichTranslations {
  copyCode: string;
  copied: string;
  lines: string;
  showAll: string;
  showLess: string;
  diagramFailed: string;
  diagram: string;
  image: string;
  openFile: string;
  open: string;
  preview: string;
  closePreview: string;
  expandPreview: string;
  restorePreview: string;
  openInFiles: string;
  download: string;
  copyPath: string;
  loading: string;
  loadFailed: string;
  zoomIn: string;
  zoomOut: string;
  zoomFit: string;
  previousPage: string;
  nextPage: string;
  pageOf: string;
  searchDocument: string;
  searchNoMatches: string;
  searchMatch: string;
  playbackFailed: string;
  noPreview: string;
  sizeLabel: string;
  typeLabel: string;
  pathLabel: string;
  largeFilePlain: string;
  send: string;
}
