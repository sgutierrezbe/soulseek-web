/* soulseek-web — Alpine component.
 *
 * Polling only runs while the relevant view is on screen *and* the document is
 * visible, so leaving the tab open on a phone doesn't drain the battery or keep
 * hammering slskd.
 */

const STORAGE = {
  lang: 'slskweb_lang',
  viewMode: 'slskweb_viewMode',
  recent: 'slskweb_recent',
  sort: 'slskweb_sort',
  volume: 'slskweb_volume',
};

const MAX_RECENT = 8;

function readStored(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function writeStored(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* Private mode or a full quota — preferences just won't persist. */
  }
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = 'GET', body, signal } = {}) {
  const response = await fetch(path, {
    method,
    signal,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }

  if (!response.ok) {
    const detail =
      (data && typeof data === 'object' && data.detail) ||
      (typeof data === 'string' && data) ||
      `HTTP ${response.status}`;
    throw new ApiError(detail, response.status);
  }
  return data;
}

function app() {
  const boot = window.__BOOT__ || {};

  return {
    /* ── shell ─────────────────────────────────────────────────────────── */
    view: 'search',
    lang: readStored(STORAGE.lang, null) || boot.lang || 'en',
    platform: boot.platform || '',
    connected: false,
    connectionError: '',
    toasts: [],
    toastSeq: 0,
    confirmState: { open: false, title: '', body: '', label: '', resolve: null },
    installPrompt: null,
    timers: [],

    /* ── auth ──────────────────────────────────────────────────────────── */
    authEnabled: !!boot.auth_enabled,
    authed: !boot.auth_enabled,
    authManagedByEnv: false,
    loginPassword: '',
    loginError: '',
    loggingIn: false,

    /* ── setup ─────────────────────────────────────────────────────────── */
    setupDone: boot.configured === true ? true : null,
    localSetup: !!boot.local_setup,
    setupForm: { slskd_url: boot.slskd_url || '', slskd_api_key: '', music_path: boot.music_path || '' },
    soulseekForm: { soulseek_username: '', soulseek_password: '', music_path: boot.music_path || '' },
    setupError: '',
    setupSaving: false,

    /* ── search ────────────────────────────────────────────────────────── */
    query: '',
    searching: false,
    searchId: null,
    searchError: '',
    albums: [],
    searchMode: 'albums',
    filterExt: '',
    sortBy: readStored(STORAGE.sort, 'relevance'),
    viewMode: readStored(STORAGE.viewMode, null) || (window.innerWidth < 640 ? 'grid' : 'list'),
    expandedAlbum: null,
    advancedSearch: !!boot.advanced_search,
    queuedFolders: [],
    recent: readStored(STORAGE.recent, []),
    trending: [],
    trendingLoaded: false,
    _searchPoll: null,
    _searchDeadline: null,

    /* ── downloads ─────────────────────────────────────────────────────── */
    downloads: [],
    downloadsError: '',
    expandedGroup: null,

    /* ── library ───────────────────────────────────────────────────────── */
    library: [],
    libraryLoading: false,
    libraryError: '',
    openAlbumEntry: null,
    albumTracks: [],
    tracksLoading: false,

    /* ── player ────────────────────────────────────────────────────────── */
    audio: null,
    player: { track: null, playing: false, position: 0, duration: 0, queue: [], index: -1 },

    /* ── settings ──────────────────────────────────────────────────────── */
    settingsForm: {
      soulseek_username: '', soulseek_password: '',
      music_path: '', slskd_url: '', slskd_api_key: '',
    },
    settingsSaving: false,
    settingsError: '',
    settingsOk: false,
    testing: false,
    testResult: '',
    newPassword: '',
    passwordSaving: false,
    appVersion: boot.version || '',
    appCommit: '',
    updating: false,
    updateLog: '',
    updateError: '',
    updateNeedsRestart: false,
    alreadyLatest: false,

    /* ── i18n ──────────────────────────────────────────────────────────── */

    t(key, vars) {
      const table = window.TRANSLATIONS[this.lang] || window.TRANSLATIONS.en;
      let value = table[key];
      if (value === undefined) value = window.TRANSLATIONS.en[key];
      if (value === undefined) return key;
      if (!vars) return value;
      return value.replace(/\{(\w+)\}/g, (match, name) =>
        vars[name] === undefined ? match : vars[name]
      );
    },

    /* ── derived ───────────────────────────────────────────────────────── */

    get visibleAlbums() {
      let list = this.filterExt
        ? this.albums.filter((a) => a.extension === this.filterExt)
        : this.albums;

      if (this.sortBy !== 'relevance') {
        const key = {
          quality: (a) => -((a.lossless ? 1e7 : 0) + (a.bitrate || 0)),
          size: (a) => -a.total_size,
          tracks: (a) => -a.track_count,
          speed: (a) => -a.upload_speed,
        }[this.sortBy];
        if (key) list = [...list].sort((a, b) => key(a) - key(b));
      }
      return list;
    },

    get visibleSongs() {
      const songs = [];
      for (const album of this.albums) {
        if (this.filterExt && album.extension !== this.filterExt) continue;
        for (const file of album.files) {
          songs.push({
            filename: file.filename,
            displayName: this.baseName(file.filename),
            size: file.size,
            extension: album.extension,
            lossless: album.lossless,
            bitrate: album.bitrate,
            username: album.username,
            folder_name: album.folder_name,
            artist_guess: album.artist_guess,
            upload_speed: album.upload_speed,
            queue_length: album.queue_length,
          });
        }
      }
      return songs;
    },

    get activeDownloads() {
      return this.downloads.filter(
        (g) => g.state === 'InProgress' || g.state === 'Queued' || g.state === 'Requested'
      ).length;
    },

    get showAdvancedHint() {
      return (
        !this.searching &&
        this.searchId &&
        !this.searchError &&
        this.searchMode === 'albums' &&
        this.visibleAlbums.length < 5
      );
    },

    /* ── lifecycle ─────────────────────────────────────────────────────── */

    async init() {
      this.setupAudio();
      this.registerServiceWorker();

      window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        this.installPrompt = event;
      });

      if (this.authEnabled) {
        const status = await api('/api/auth/status').catch(() => null);
        this.authed = status ? status.authenticated : false;
        this.authManagedByEnv = status ? status.managed_by_env : false;
        if (!this.authed) return;
      }

      await this.start();
    },

    /* Everything that needs a usable session, split out so login can call it. */
    async start() {
      if (this.setupDone === null) await this.checkSetup();
      this.loadVersion();
      this.loadTrending();

      if (this.setupDone) this.checkStatus();

      // One master timer instead of several: cheaper, and easy to suspend when
      // the page is hidden.
      this.addTimer(
        setInterval(() => {
          if (document.hidden || !this.authed || !this.setupDone) return;
          if (this.view === 'downloads') this.loadDownloads({ quiet: true });
        }, 2500)
      );
      this.addTimer(
        setInterval(() => {
          if (document.hidden || !this.authed || !this.setupDone) return;
          this.checkStatus();
        }, 20000)
      );

      document.addEventListener('visibilitychange', () => {
        if (document.hidden || !this.authed) return;
        this.checkStatus();
        if (this.view === 'downloads') this.loadDownloads({ quiet: true });
      });
    },

    addTimer(id) {
      this.timers.push(id);
    },

    registerServiceWorker() {
      if (!('serviceWorker' in navigator)) return;
      window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => {
          /* Not fatal — the app works fine without offline caching. */
        });
      });
    },

    async promptInstall() {
      if (!this.installPrompt) return;
      this.installPrompt.prompt();
      await this.installPrompt.userChoice.catch(() => null);
      this.installPrompt = null;
    },

    /* ── navigation ────────────────────────────────────────────────────── */

    go(view) {
      this.view = view;
      if (view === 'downloads') this.loadDownloads();
      if (view === 'library' && !this.library.length) this.loadLibrary();
      if (view === 'settings') this.loadSettings();
    },

    /* ── auth ──────────────────────────────────────────────────────────── */

    async login() {
      this.loginError = '';
      this.loggingIn = true;
      try {
        await api('/api/auth/login', { method: 'POST', body: { password: this.loginPassword } });
        this.authed = true;
        this.loginPassword = '';
        await this.start();
      } catch (error) {
        this.loginError = error.status === 401 ? this.t('loginWrong') : error.message;
      } finally {
        this.loggingIn = false;
      }
    },

    async logout() {
      await api('/api/auth/logout', { method: 'POST' }).catch(() => null);
      window.location.reload();
    },

    async savePassword() {
      const password = this.newPassword.trim();
      if (password && password.length < 6) {
        this.settingsError = this.t('passwordTooShort');
        return;
      }
      this.passwordSaving = true;
      this.settingsError = '';
      try {
        const result = await api('/api/auth/password', { method: 'POST', body: { password } });
        this.authEnabled = result.enabled;
        this.authed = true;
        this.newPassword = '';
        this.toast(this.t(result.enabled ? 'passwordSet' : 'passwordRemoved'));
      } catch (error) {
        this.settingsError = error.message;
      } finally {
        this.passwordSaving = false;
      }
    },

    /* ── setup ─────────────────────────────────────────────────────────── */

    async checkSetup() {
      try {
        const data = await api('/api/setup/status');
        this.localSetup = !!data.local_setup;
        this.platform = data.platform || '';
        this.setupDone = !!data.configured;
        this.advancedSearch = !!data.advanced_search;
        if (data.slskd_url) this.setupForm.slskd_url = data.slskd_url;
        if (data.music_path) {
          this.setupForm.music_path = data.music_path;
          this.soulseekForm.music_path = data.music_path;
        }
      } catch {
        this.setupDone = false;
      }
    },

    async saveSetup() {
      this.setupError = '';
      this.setupSaving = true;
      try {
        const data = await api('/api/setup/credentials', { method: 'POST', body: this.setupForm });
        if (data.ok) {
          this.setupDone = true;
          this.checkStatus();
          this.toast(this.t('settingsSaved'));
        } else {
          this.setupError = data.error || this.t('unknownError');
        }
      } catch (error) {
        this.setupError = error.message || this.t('connError');
      } finally {
        this.setupSaving = false;
      }
    },

    async saveLocalSetup() {
      this.setupError = '';
      this.setupSaving = true;
      try {
        const data = await api('/api/setup/soulseek', { method: 'POST', body: this.soulseekForm });
        if (data.ok) {
          this.setupDone = true;
          this.checkStatus();
          this.toast(this.t('settingsSaved'));
        } else {
          this.setupError = data.error || this.t('unknownError');
        }
      } catch (error) {
        this.setupError = error.message || this.t('connError');
      } finally {
        this.setupSaving = false;
      }
    },

    async checkStatus() {
      try {
        await api('/api/downloads/');
        this.connected = true;
        this.connectionError = '';
      } catch (error) {
        this.connected = false;
        this.connectionError = error.status === 502 ? error.message : '';
      }
    },

    /* ── search ────────────────────────────────────────────────────────── */

    async doSearch(term) {
      const query = (term === undefined ? this.query : term).trim();
      if (!query) return;

      this.query = query;
      this.stopSearch({ silent: true });
      this.albums = [];
      this.searchError = '';
      this.expandedAlbum = null;
      this.queuedFolders = [];
      this.searching = true;
      this.rememberSearch(query);

      // Dismiss the on-screen keyboard so results are visible immediately.
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();

      try {
        const data = await api('/api/search/', { method: 'POST', body: { query } });
        this.searchId = data.search_id;
        this.pollResults();
      } catch (error) {
        this.searching = false;
        this.searchError = error.message || this.t('searchFailed');
      }
    },

    pollResults() {
      // Give up after 45s so a peer-starved search can't spin forever.
      this._searchDeadline = Date.now() + 45000;
      this._searchPoll = setInterval(async () => {
        if (!this.searchId) return this.stopPolling();
        if (Date.now() > this._searchDeadline) {
          this.searching = false;
          return this.stopPolling();
        }
        try {
          const data = await api(
            `/api/search/${this.searchId}?raw=${this.advancedSearch}`
          );
          this.albums = data.albums || [];
          if (data.error) {
            this.searchError = data.error;
            this.searching = false;
            this.stopPolling();
          } else if (data.state && data.state.includes('Completed')) {
            this.searching = false;
            this.stopPolling();
          }
        } catch {
          /* A single failed poll is not fatal; the next one may succeed. */
        }
      }, 1500);
      this.addTimer(this._searchPoll);
    },

    stopPolling() {
      if (this._searchPoll) {
        clearInterval(this._searchPoll);
        this._searchPoll = null;
      }
    },

    stopSearch({ silent = false } = {}) {
      this.stopPolling();
      this.searching = false;
      if (this.searchId) {
        api(`/api/search/${this.searchId}`, { method: 'DELETE' }).catch(() => null);
        if (!silent) this.searchId = null;
      }
    },

    clearSearch() {
      this.stopSearch();
      this.query = '';
      this.albums = [];
      this.searchId = null;
      this.searchError = '';
    },

    rememberSearch(query) {
      const next = [query, ...this.recent.filter((item) => item !== query)].slice(0, MAX_RECENT);
      this.recent = next;
      writeStored(STORAGE.recent, next);
    },

    clearRecent() {
      this.recent = [];
      writeStored(STORAGE.recent, []);
    },

    searchTrending(album) {
      this.doSearch(album.artist ? `${album.artist} ${album.title}` : album.title);
    },

    async loadTrending() {
      try {
        this.trending = await api('/api/covers/trending');
      } catch {
        this.trending = [];
      } finally {
        this.trendingLoaded = true;
      }
    },

    setViewMode(mode) {
      this.viewMode = mode;
      writeStored(STORAGE.viewMode, mode);
    },

    setSort(value) {
      this.sortBy = value;
      writeStored(STORAGE.sort, value);
    },

    async toggleAdvanced() {
      this.advancedSearch = !this.advancedSearch;
      await this.savePreferences();
      if (this.query.trim()) this.doSearch();
    },

    /* ── downloading ───────────────────────────────────────────────────── */

    async downloadFolder(album) {
      if (this.queuedFolders.includes(album.folder_path)) return;
      this.queuedFolders = [...this.queuedFolders, album.folder_path];
      try {
        await api('/api/downloads/folder', {
          method: 'POST',
          body: { username: album.username, files: album.files },
        });
        this.toast(this.t('downloadingAlbum', { name: album.folder_name }));
      } catch (error) {
        this.queuedFolders = this.queuedFolders.filter((p) => p !== album.folder_path);
        this.toast(error.message || this.t('dlError'), true);
      }
    },

    async downloadSingle(username, file) {
      try {
        await api('/api/downloads/', {
          method: 'POST',
          body: { username, filename: file.filename, size: file.size },
        });
        this.toast(this.baseName(file.filename));
      } catch (error) {
        this.toast(error.message || this.t('dlError'), true);
      }
    },

    async loadDownloads({ quiet = false } = {}) {
      try {
        this.downloads = await api('/api/downloads/');
        this.downloadsError = '';
        this.connected = true;
      } catch (error) {
        if (!quiet) this.downloadsError = error.message || this.t('connError');
        this.connected = false;
      }
    },

    async deleteFolder(group) {
      const ok = await this.ask(
        this.t('deleteTitle'),
        this.t('deleteBody', { name: group.folder_name }),
        this.t('delete')
      );
      if (!ok) return;

      try {
        await api('/api/downloads/folder', {
          method: 'DELETE',
          body: {
            username: group.username,
            file_ids: group.file_ids,
            local_paths: group.local_paths,
            folder_name: group.folder_name,
            filenames: group.files.map((f) => f.filename),
          },
        });
        this.toast(this.t('deleted', { name: group.folder_name }));
        await this.loadDownloads();
      } catch (error) {
        this.toast(error.message || this.t('deleteError'), true);
      }
    },

    async cancelFile(group, file) {
      try {
        await api(`/api/downloads/${encodeURIComponent(group.username)}/${file.file_id}`, {
          method: 'DELETE',
        });
        this.toast(this.t('cancelled'));
        await this.loadDownloads();
      } catch (error) {
        this.toast(error.message || this.t('unknownError'), true);
      }
    },

    async clearCompleted() {
      const ok = await this.ask(
        this.t('clearCompletedTitle'),
        this.t('clearCompletedBody'),
        this.t('clearCompleted')
      );
      if (!ok) return;
      try {
        await api('/api/downloads/completed', { method: 'DELETE' });
        this.toast(this.t('cleared'));
        await this.loadDownloads();
      } catch (error) {
        this.toast(error.message || this.t('unknownError'), true);
      }
    },

    /* ── library ───────────────────────────────────────────────────────── */

    async loadLibrary(refresh = false) {
      this.libraryLoading = true;
      this.libraryError = '';
      try {
        this.library = await api(`/api/library/albums${refresh ? '?refresh=true' : ''}`);
      } catch (error) {
        this.libraryError = error.message || this.t('connError');
      } finally {
        this.libraryLoading = false;
      }
    },

    async openAlbum(entry) {
      this.openAlbumEntry = entry;
      this.albumTracks = [];
      this.tracksLoading = true;
      try {
        this.albumTracks = await api(`/api/library/tracks?path=${encodeURIComponent(entry.path)}`);
      } catch (error) {
        this.toast(error.message || this.t('connError'), true);
      } finally {
        this.tracksLoading = false;
      }
    },

    closeAlbum() {
      this.openAlbumEntry = null;
      this.albumTracks = [];
    },

    /* ── player ────────────────────────────────────────────────────────── */

    setupAudio() {
      const audio = new Audio();
      audio.preload = 'metadata';
      audio.volume = readStored(STORAGE.volume, 1);

      audio.addEventListener('timeupdate', () => {
        this.player.position = audio.currentTime;
      });
      audio.addEventListener('durationchange', () => {
        this.player.duration = Number.isFinite(audio.duration) ? audio.duration : 0;
      });
      audio.addEventListener('play', () => { this.player.playing = true; });
      audio.addEventListener('pause', () => { this.player.playing = false; });
      audio.addEventListener('ended', () => this.playNext());
      audio.addEventListener('error', () => {
        if (this.player.track) this.toast(this.t('unknownError'), true);
      });

      this.audio = audio;

      // Lock-screen / headphone controls on phones.
      if ('mediaSession' in navigator) {
        navigator.mediaSession.setActionHandler('play', () => this.togglePlay());
        navigator.mediaSession.setActionHandler('pause', () => this.togglePlay());
        navigator.mediaSession.setActionHandler('nexttrack', () => this.playNext());
        navigator.mediaSession.setActionHandler('previoustrack', () => this.playPrevious());
      }
    },

    playTrack(track, queue) {
      const list = queue || this.albumTracks || [];
      this.player.queue = list;
      this.player.index = list.findIndex((item) => item.path === track.path);
      this.player.track = track;
      this.audio.src = `/api/stream/audio?path=${encodeURIComponent(track.path)}`;
      this.audio.play().catch(() => this.toast(this.t('unknownError'), true));
      this.updateMediaSession(track);
    },

    updateMediaSession(track) {
      if (!('mediaSession' in navigator)) return;
      const album = this.openAlbumEntry || {};
      navigator.mediaSession.metadata = new MediaMetadata({
        title: track.title || track.filename,
        artist: track.artist || album.artist || '',
        album: album.album || '',
        artwork: [
          {
            src: `/api/covers/local?path=${encodeURIComponent(track.path)}`,
            sizes: '512x512',
            type: 'image/jpeg',
          },
        ],
      });
    },

    togglePlay() {
      if (!this.player.track) return;
      if (this.audio.paused) this.audio.play().catch(() => null);
      else this.audio.pause();
    },

    playNext() {
      const { queue, index } = this.player;
      if (index >= 0 && index + 1 < queue.length) this.playTrack(queue[index + 1], queue);
      else this.player.playing = false;
    },

    playPrevious() {
      // Restart the current track first, the way most players behave.
      if (this.audio.currentTime > 3) {
        this.audio.currentTime = 0;
        return;
      }
      const { queue, index } = this.player;
      if (index > 0) this.playTrack(queue[index - 1], queue);
      else this.audio.currentTime = 0;
    },

    seek(event) {
      if (!this.player.duration) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
      this.audio.currentTime = ratio * this.player.duration;
    },

    closePlayer() {
      this.audio.pause();
      this.audio.removeAttribute('src');
      this.audio.load();
      this.player = { track: null, playing: false, position: 0, duration: 0, queue: [], index: -1 };
    },

    isPlaying(track) {
      return !!this.player.track && this.player.track.path === track.path;
    },

    /* ── settings ──────────────────────────────────────────────────────── */

    async loadSettings() {
      try {
        const data = await api('/api/setup/settings');
        this.platform = data.platform || this.platform;
        this.localSetup = !!data.local_setup;
        this.settingsForm = {
          soulseek_username: data.soulseek_username || '',
          soulseek_password: data.soulseek_password || '',
          music_path: data.music_path || '',
          slskd_url: data.slskd_url || '',
          slskd_api_key: data.slskd_api_key || '',
        };
        this.advancedSearch = !!data.advanced_search;
        this.authEnabled = !!data.auth_enabled;
        if (data.lang && !readStored(STORAGE.lang, null)) this.lang = data.lang;
        this.settingsError = '';
        this.settingsOk = false;
        this.testResult = '';
      } catch {
        /* Leave the form as-is; the user can still edit and save. */
      }
    },

    async saveSettings() {
      this.settingsError = '';
      this.settingsOk = false;
      this.settingsSaving = true;
      try {
        const path = this.localSetup ? '/api/setup/soulseek' : '/api/setup/credentials';
        const body = this.localSetup
          ? {
              soulseek_username: this.settingsForm.soulseek_username,
              soulseek_password: this.settingsForm.soulseek_password,
              music_path: this.settingsForm.music_path,
            }
          : { ...this.settingsForm };

        const data = await api(path, { method: 'POST', body });
        if (data.ok) {
          this.settingsOk = true;
          this.toast(this.t('settingsSaved'));
          this.checkStatus();
        } else {
          this.settingsError = data.error || this.t('unknownError');
        }
      } catch (error) {
        this.settingsError = error.message || this.t('connError');
      } finally {
        this.settingsSaving = false;
      }
    },

    async testConnection() {
      this.testing = true;
      this.testResult = '';
      try {
        const data = await api('/api/setup/test', {
          method: 'POST',
          body: {
            slskd_url: this.settingsForm.slskd_url || this.setupForm.slskd_url,
            slskd_api_key: this.settingsForm.slskd_api_key || this.setupForm.slskd_api_key,
          },
        });
        this.testResult = data.ok
          ? this.t('testOk', { version: data.version || '' })
          : `${this.t('testFail')} — ${data.error}`;
      } catch (error) {
        this.testResult = `${this.t('testFail')} — ${error.message}`;
      } finally {
        this.testing = false;
      }
    },

    async savePreferences() {
      await api('/api/setup/preferences', {
        method: 'POST',
        body: { advanced_search: this.advancedSearch, lang: this.lang },
      }).catch(() => null);
    },

    setLang(lang) {
      this.lang = lang;
      writeStored(STORAGE.lang, lang);
      document.documentElement.lang = lang;
      this.savePreferences();
    },

    async loadVersion() {
      try {
        const data = await api('/api/setup/version');
        this.appVersion = data.version;
        this.appCommit = data.commit;
      } catch {
        /* Version display is cosmetic. */
      }
    },

    async triggerUpdate() {
      this.updating = true;
      this.updateLog = '';
      this.updateError = '';
      this.updateNeedsRestart = false;
      try {
        const data = await api('/api/setup/update', { method: 'POST' });
        this.alreadyLatest = data.already_latest;
        if (data.already_latest) {
          this.updateLog = `${this.t('upToDate')} (${data.version || this.appVersion})`;
        } else {
          this.updateLog = `${data.pull_output || ''}\n→ ${data.version || '?'}`;
          if (data.needs_restart) {
            this.updateNeedsRestart = true;
          } else {
            this.toast(this.t('updatedRestarting'));
            setTimeout(() => window.location.reload(), 4000);
          }
        }
        this.appVersion = data.version || this.appVersion;
      } catch (error) {
        this.updateError = error.status ? error.message : this.t('updateConnError');
      } finally {
        this.updating = false;
      }
    },

    /* ── UI helpers ────────────────────────────────────────────────────── */

    toast(message, isError = false) {
      const id = ++this.toastSeq;
      this.toasts.push({ id, message, isError });
      setTimeout(() => {
        this.toasts = this.toasts.filter((item) => item.id !== id);
      }, 3800);
    },

    ask(title, body, label) {
      return new Promise((resolve) => {
        this.confirmState = { open: true, title, body, label: label || this.t('confirmBtn'), resolve };
      });
    },

    resolveConfirm(value) {
      const { resolve } = this.confirmState;
      this.confirmState = { ...this.confirmState, open: false, resolve: null };
      if (resolve) resolve(value);
    },

    /* ── formatting ────────────────────────────────────────────────────── */

    baseName(path) {
      return String(path).split('\\').pop().split('/').pop();
    },

    formatSize(bytes) {
      if (!bytes) return '—';
      if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
      if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
      return `${(bytes / 1e3).toFixed(0)} KB`;
    },

    formatSpeed(bytesPerSecond) {
      if (!bytesPerSecond) return '—';
      if (bytesPerSecond >= 1e6) return `${(bytesPerSecond / 1e6).toFixed(1)} MB/s`;
      if (bytesPerSecond >= 1e3) return `${(bytesPerSecond / 1e3).toFixed(0)} KB/s`;
      return `${bytesPerSecond} B/s`;
    },

    formatTime(seconds) {
      if (!seconds || !Number.isFinite(seconds)) return '0:00';
      const total = Math.floor(seconds);
      const minutes = Math.floor(total / 60);
      return `${minutes}:${String(total % 60).padStart(2, '0')}`;
    },

    formatEta(seconds) {
      if (!seconds || !Number.isFinite(seconds)) return '';
      if (seconds < 60) return `${Math.round(seconds)}s`;
      if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
      return `${(seconds / 3600).toFixed(1)}h`;
    },

    extClass(extension) {
      if (extension === 'MP3') return 'is-mp3';
      return ['FLAC', 'WAV', 'AIFF', 'APE', 'WV'].includes(extension) ? 'is-lossless' : '';
    },

    stateLabel(state) {
      const key = String(state || '').split(',')[0].trim();
      return (
        {
          Completed: '✓',
          InProgress: '↓',
          Queued: '⏸',
          Requested: '⟳',
          Errored: '✗',
          Cancelled: '✕',
        }[key] || ''
      ) + ' ' + key;
    },

    stateClass(state) {
      return 'state-' + String(state || '').split(',')[0].trim();
    },

    coverForSearch(album) {
      const params = new URLSearchParams({
        artist: album.artist_guess || '',
        album: album.folder_name || '',
      });
      return `/api/covers/search?${params}`;
    },

    coverForFolder(folderName) {
      return `/api/covers/folder?folder_name=${encodeURIComponent(folderName)}`;
    },

    coverForLibrary(entry) {
      return `/api/covers/folder?folder_name=${encodeURIComponent(entry.album)}`;
    },
  };
}

window.app = app;
