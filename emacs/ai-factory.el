;;; ai-factory.el --- Emacs cockpit for ai-factory runs -*- lexical-binding: t; -*-

;; Author: ai-factory contributors
;; Version: 0.1.0
;; Package-Requires: ((emacs "27.1"))
;; Keywords: tools, ai, convenience
;; URL: https://github.com/ozubko/ai-factory

;;; Commentary:

;; This package is a thin Emacs cockpit for the ai-factory CLI.  It does not
;; reimplement factory logic in Emacs Lisp.  It calls `ai-factory`, reads run
;; artifacts from the State Dir, and opens plans, reports, diffs, logs, and
;; worktrees in normal Emacs buffers.

;;; Code:

(require 'button)
(require 'compile)
(require 'json)
(require 'tabulated-list)
(require 'vc)

(defgroup ai-factory nil
  "Emacs cockpit for ai-factory runs."
  :group 'tools
  :prefix "ai-factory-")

(defcustom ai-factory-command "ai-factory"
  "Command used to run the ai-factory CLI."
  :type 'string
  :group 'ai-factory)

(defcustom ai-factory-state-dir nil
  "Optional explicit ai-factory State Dir.

When nil, the package follows the CLI's default discovery:
`AI_FACTORY_STATE_DIR`, then `$XDG_STATE_HOME/ai-factory`, then
`~/.local/state/ai-factory`."
  :type '(choice (const :tag "Use CLI default" nil) directory)
  :group 'ai-factory)

(defcustom ai-factory-default-backend "fake"
  "Default backend offered by interactive run/plan commands."
  :type 'string
  :group 'ai-factory)

(defcustom ai-factory-buffer-name "*AI Factory Runs*"
  "Buffer name used for the run list."
  :type 'string
  :group 'ai-factory)

(defun ai-factory--state-dir ()
  "Return the ai-factory State Dir as a directory path."
  (file-name-as-directory
   (expand-file-name
    (or ai-factory-state-dir
        (getenv "AI_FACTORY_STATE_DIR")
        (let ((xdg (getenv "XDG_STATE_HOME")))
          (if xdg
              (expand-file-name "ai-factory" xdg)
            (expand-file-name "~/.local/state/ai-factory")))))))

(defun ai-factory--runs-dir ()
  "Return the directory containing ai-factory runs."
  (expand-file-name "runs" (ai-factory--state-dir)))

(defun ai-factory--metadata-path (run-id)
  "Return the metadata.json path for RUN-ID."
  (expand-file-name "metadata.json" (expand-file-name run-id (ai-factory--runs-dir))))

(defun ai-factory--run-dir (run-id)
  "Return the run directory for RUN-ID."
  (expand-file-name run-id (ai-factory--runs-dir)))

(defun ai-factory--read-json-file (path)
  "Read PATH as JSON and return an alist.
Return nil if the file does not exist or cannot be parsed."
  (when (file-readable-p path)
    (condition-case nil
        (with-temp-buffer
          (insert-file-contents path)
          (json-parse-buffer :object-type 'alist :array-type 'list :null-object nil :false-object nil))
      (error nil))))

(defun ai-factory--metadata (run-id)
  "Return metadata alist for RUN-ID, or nil."
  (ai-factory--read-json-file (ai-factory--metadata-path run-id)))

(defun ai-factory--get (key alist &optional fallback)
  "Get KEY from ALIST, returning FALLBACK when absent."
  (or (alist-get key alist) fallback))

(defun ai-factory--nested-get (keys alist &optional fallback)
  "Get nested KEYS from ALIST, returning FALLBACK when absent."
  (let ((value alist))
    (while (and keys (listp value))
      (setq value (alist-get (pop keys) value)))
    (or value fallback)))

(defun ai-factory--list-run-ids ()
  "Return known run ids from the State Dir."
  (let ((runs-dir (ai-factory--runs-dir)))
    (if (file-directory-p runs-dir)
        (sort
         (delq nil
               (mapcar (lambda (path)
                         (when (file-readable-p (expand-file-name "metadata.json" path))
                           (file-name-nondirectory (directory-file-name path))))
                       (directory-files runs-dir t "^[^.].*")))
         #'string<)
      nil)))

(defun ai-factory--read-run-id ()
  "Read a run id interactively."
  (let ((runs (ai-factory--list-run-ids)))
    (unless runs
      (user-error "No ai-factory runs found under %s" (ai-factory--runs-dir)))
    (completing-read "Run ID: " runs nil t)))

(defun ai-factory--default-repo ()
  "Return a reasonable default target repo directory."
  (or (vc-root-dir) default-directory))

(defun ai-factory--args-with-state-dir (args)
  "Append `--state-dir` to ARGS when `ai-factory-state-dir` is set."
  (if ai-factory-state-dir
      (append args (list "--state-dir" (ai-factory--state-dir)))
    args))

(defun ai-factory--start-cli (name args)
  "Start ai-factory CLI asynchronously with NAME and ARGS.
The command runs in `compilation-mode` so long-running agent output is visible."
  (let ((command (mapconcat #'shell-quote-argument (cons ai-factory-command args) " ")))
    (compilation-start command 'compilation-mode
                       (lambda (_) (format "*AI Factory: %s*" name)))))

(defun ai-factory-run (repo task backend)
  "Run ai-factory against REPO for TASK using BACKEND.
An empty BACKEND lets the CLI/config choose the backend."
  (interactive
   (list (read-directory-name "Target repo: " (ai-factory--default-repo))
         (read-string "Task: ")
         (read-string "Backend (empty = config/manual): " ai-factory-default-backend)))
  (let ((args (list "run" (expand-file-name repo) task)))
    (unless (string-empty-p backend)
      (setq args (append args (list "--backend" backend))))
    (ai-factory--start-cli "run" (ai-factory--args-with-state-dir args))))

(defun ai-factory-plan (repo task backend)
  "Create a staged ai-factory plan run for REPO and TASK using BACKEND."
  (interactive
   (list (read-directory-name "Target repo: " (ai-factory--default-repo))
         (read-string "Task: ")
         (read-string "Backend: " ai-factory-default-backend)))
  (when (string-empty-p backend)
    (user-error "Staged `plan` requires a backend, e.g. fake, codex, or claude"))
  (ai-factory--start-cli
   "plan"
   (ai-factory--args-with-state-dir
    (list "plan" (expand-file-name repo) task "--backend" backend))))

(defun ai-factory-implement (run-id &optional review)
  "Continue RUN-ID through implement/verify/fix-loop.
With prefix argument REVIEW, also run the review phase."
  (interactive (list (ai-factory--read-run-id) current-prefix-arg))
  (ai-factory--start-cli
   "implement"
   (ai-factory--args-with-state-dir
    (append (list "implement" run-id) (when review (list "--review"))))))

(defun ai-factory-review (run-id)
  "Run the read-only review phase for RUN-ID."
  (interactive (list (ai-factory--read-run-id)))
  (ai-factory--start-cli "review" (ai-factory--args-with-state-dir (list "review" run-id))))

(defun ai-factory-resume (run-id &optional discard)
  "Resume RUN-ID.
With prefix argument DISCARD, pass `--discard-phase-changes`."
  (interactive (list (ai-factory--read-run-id) current-prefix-arg))
  (ai-factory--start-cli
   "resume"
   (ai-factory--args-with-state-dir
    (append (list "resume" run-id) (when discard (list "--discard-phase-changes"))))))

(defun ai-factory-clean (run-id)
  "Clean RUN-ID after confirmation."
  (interactive (list (ai-factory--read-run-id)))
  (when (yes-or-no-p (format "Clean ai-factory run %s? " run-id))
    (ai-factory--start-cli "clean" (ai-factory--args-with-state-dir (list "clean" run-id)))))

(defun ai-factory-open-artifact (run-id filename)
  "Open FILENAME from RUN-ID's run directory."
  (let ((path (expand-file-name filename (ai-factory--run-dir run-id))))
    (unless (file-exists-p path)
      (user-error "Artifact does not exist: %s" path))
    (find-file path)))

(defun ai-factory-open-plan (run-id)
  "Open RUN-ID's plan.md."
  (interactive (list (ai-factory--read-run-id)))
  (ai-factory-open-artifact run-id "plan.md"))

(defun ai-factory-open-report (run-id)
  "Open RUN-ID's report.md."
  (interactive (list (ai-factory--read-run-id)))
  (ai-factory-open-artifact run-id "report.md"))

(defun ai-factory-open-diff (run-id)
  "Open RUN-ID's diff.patch."
  (interactive (list (ai-factory--read-run-id)))
  (ai-factory-open-artifact run-id "diff.patch"))

(defun ai-factory-open-pr-body (run-id)
  "Open RUN-ID's pr-body.md."
  (interactive (list (ai-factory--read-run-id)))
  (ai-factory-open-artifact run-id "pr-body.md"))

(defun ai-factory-open-worktree (run-id)
  "Open RUN-ID's worktree in Dired."
  (interactive (list (ai-factory--read-run-id)))
  (let* ((metadata (ai-factory--metadata run-id))
         (worktree (ai-factory--get 'worktree_path metadata)))
    (unless (and worktree (file-directory-p worktree))
      (user-error "Run has no readable worktree: %s" run-id))
    (dired worktree)))

(defun ai-factory-magit-worktree (run-id)
  "Open RUN-ID's worktree in Magit, or Dired if Magit is unavailable."
  (interactive (list (ai-factory--read-run-id)))
  (let* ((metadata (ai-factory--metadata run-id))
         (worktree (ai-factory--get 'worktree_path metadata)))
    (unless (and worktree (file-directory-p worktree))
      (user-error "Run has no readable worktree: %s" run-id))
    (if (fboundp 'magit-status)
        (magit-status worktree)
      (message "Magit is not loaded; opening Dired instead")
      (dired worktree))))

(defvar ai-factory-runs-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'ai-factory-open-run-at-point)
    (define-key map (kbd "g") #'ai-factory-list)
    (define-key map (kbd "r") #'ai-factory-run)
    (define-key map (kbd "p") #'ai-factory-plan)
    (define-key map (kbd "i") #'ai-factory-implement-at-point)
    (define-key map (kbd "v") #'ai-factory-review-at-point)
    (define-key map (kbd "R") #'ai-factory-open-report-at-point)
    (define-key map (kbd "P") #'ai-factory-open-plan-at-point)
    (define-key map (kbd "D") #'ai-factory-open-diff-at-point)
    (define-key map (kbd "m") #'ai-factory-magit-worktree-at-point)
    (define-key map (kbd "c") #'ai-factory-clean-at-point)
    map)
  "Keymap for `ai-factory-runs-mode`.")

(define-derived-mode ai-factory-runs-mode tabulated-list-mode "AI Factory Runs"
  "Major mode for browsing ai-factory runs."
  (setq tabulated-list-format
        [("Run ID" 28 t)
         ("Outcome" 24 t)
         ("Risk" 8 t)
         ("Backend" 12 t)
         ("Target" 40 t)])
  (setq tabulated-list-padding 2)
  (setq tabulated-list-sort-key (cons "Run ID" nil))
  (tabulated-list-init-header))

(defun ai-factory--entry-for-run (run-id)
  "Return a tabulated-list entry for RUN-ID."
  (let* ((metadata (ai-factory--metadata run-id))
         (risk (ai-factory--nested-get '(risk level) metadata "")))
    (list run-id
          (vector run-id
                  (format "%s" (ai-factory--get 'outcome metadata ""))
                  (format "%s" risk)
                  (format "%s" (ai-factory--get 'backend metadata ""))
                  (abbreviate-file-name (format "%s" (ai-factory--get 'target_repo metadata "")))))))

;;;###autoload
(defun ai-factory-list ()
  "Open a buffer listing ai-factory runs."
  (interactive)
  (let ((buffer (get-buffer-create ai-factory-buffer-name)))
    (with-current-buffer buffer
      (ai-factory-runs-mode)
      (setq tabulated-list-entries (mapcar #'ai-factory--entry-for-run (ai-factory--list-run-ids)))
      (tabulated-list-print t))
    (pop-to-buffer buffer)))

(defun ai-factory--run-id-at-point ()
  "Return the run id at point in the run list."
  (or (tabulated-list-get-id)
      (user-error "No run at point")))

(defun ai-factory-open-run-at-point ()
  "Open the run at point."
  (interactive)
  (ai-factory-open-run (ai-factory--run-id-at-point)))

(defun ai-factory-implement-at-point ()
  "Implement the run at point."
  (interactive)
  (ai-factory-implement (ai-factory--run-id-at-point)))

(defun ai-factory-review-at-point ()
  "Review the run at point."
  (interactive)
  (ai-factory-review (ai-factory--run-id-at-point)))

(defun ai-factory-open-report-at-point ()
  "Open report.md for the run at point."
  (interactive)
  (ai-factory-open-report (ai-factory--run-id-at-point)))

(defun ai-factory-open-plan-at-point ()
  "Open plan.md for the run at point."
  (interactive)
  (ai-factory-open-plan (ai-factory--run-id-at-point)))

(defun ai-factory-open-diff-at-point ()
  "Open diff.patch for the run at point."
  (interactive)
  (ai-factory-open-diff (ai-factory--run-id-at-point)))

(defun ai-factory-magit-worktree-at-point ()
  "Open Magit for the run at point."
  (interactive)
  (ai-factory-magit-worktree (ai-factory--run-id-at-point)))

(defun ai-factory-clean-at-point ()
  "Clean the run at point."
  (interactive)
  (ai-factory-clean (ai-factory--run-id-at-point)))

(defun ai-factory--insert-action (label action)
  "Insert clickable LABEL that calls ACTION."
  (insert-text-button label 'action (lambda (_) (funcall action)) 'follow-link t)
  (insert "\n"))

;;;###autoload
(defun ai-factory-open-run (run-id)
  "Open a detail buffer for RUN-ID."
  (interactive (list (ai-factory--read-run-id)))
  (let* ((metadata (ai-factory--metadata run-id))
         (buffer (get-buffer-create (format "*AI Factory: %s*" run-id)))
         (worktree (ai-factory--get 'worktree_path metadata "")))
    (unless metadata
      (user-error "Could not read metadata for run %s" run-id))
    (with-current-buffer buffer
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (format "AI Factory Run: %s\n\n" run-id))
        (insert (format "Outcome:  %s\n" (ai-factory--get 'outcome metadata "")))
        (insert (format "Reason:   %s\n" (ai-factory--get 'outcome_reason metadata "")))
        (insert (format "Risk:     %s\n" (ai-factory--nested-get '(risk level) metadata "")))
        (insert (format "Backend:  %s\n" (ai-factory--get 'backend metadata "")))
        (insert (format "Target:   %s\n" (ai-factory--get 'target_repo metadata "")))
        (insert (format "Worktree: %s\n" worktree))
        (insert "\nActions:\n")
        (ai-factory--insert-action "Open plan.md" (lambda () (ai-factory-open-plan run-id)))
        (ai-factory--insert-action "Open report.md" (lambda () (ai-factory-open-report run-id)))
        (ai-factory--insert-action "Open diff.patch" (lambda () (ai-factory-open-diff run-id)))
        (ai-factory--insert-action "Open pr-body.md" (lambda () (ai-factory-open-pr-body run-id)))
        (ai-factory--insert-action "Open worktree in Dired" (lambda () (ai-factory-open-worktree run-id)))
        (ai-factory--insert-action "Open worktree in Magit" (lambda () (ai-factory-magit-worktree run-id)))
        (ai-factory--insert-action "Implement this run" (lambda () (ai-factory-implement run-id)))
        (ai-factory--insert-action "Review this run" (lambda () (ai-factory-review run-id)))
        (ai-factory--insert-action "Resume this run" (lambda () (ai-factory-resume run-id)))
        (ai-factory--insert-action "Clean this run" (lambda () (ai-factory-clean run-id)))
        (special-mode)))
    (pop-to-buffer buffer)))

(provide 'ai-factory)

;;; ai-factory.el ends here
