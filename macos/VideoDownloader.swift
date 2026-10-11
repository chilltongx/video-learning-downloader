import AppKit
import Foundation

extension String {
    var expandingTildeInPath: String { (self as NSString).expandingTildeInPath }
}

private final class ArtifactButton: NSButton {
    var fileURL: URL?
}

private final class TopClipView: NSClipView {
    override var isFlipped: Bool { true }
}

@main
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var urlTextView: NSTextView!
    private var logTextView: NSTextView!
    private var outputField: NSTextField!
    private var modeControl: NSSegmentedControl!
    private var qualityPopup: NSPopUpButton!
    private var audioPopup: NSPopUpButton!
    private var languagePopup: NSPopUpButton!
    private var coverCheck: NSButton!
    private var transcriptCheck: NSButton!
    private var subtitleCheck: NSButton!
    private var timestampCheck: NSButton!
    private var qualityRow: NSStackView!
    private var audioRow: NSStackView!
    private var languageRow: NSStackView!
    private var transcriptPathLabel: NSTextField!
    private var guestField: NSTextField!
    private var guestRow: NSStackView!
    private var optionRow: NSStackView!
    private var hintLabel: NSTextField!
    private var statusLabel: NSTextField!
    private var titleLabel: NSTextField!
    private var detailLabel: NSTextField!
    private var progress: NSProgressIndicator!
    private var downloadButton: NSButton!
    private var stopButton: NSButton!
    private var clearButton: NSButton!
    private var chooseButton: NSButton!
    private var logsButton: NSButton!
    private var logScroll: NSScrollView!
    private var resultStack: NSStackView!
    private var currentProcess: Process?
    private var previewWindow: NSWindow?
    private var outputBuffer = Data()
    private var receivedDone = false
    private var resultCount = 0
    private var currentMode = "video"
    private var itemPrefix = ""
    private let modes = ["audio", "text", "video"]
    private let defaultOutputPath = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Movies").path

    static func main() {
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.regular)
        _ = NSApplicationMain(CommandLine.argc, CommandLine.unsafeArgv)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let url = Bundle.main.url(forResource: "AppIcon", withExtension: "icns") {
            NSApp.applicationIconImage = NSImage(contentsOf: url)
        }
        installMainMenu()
        buildWindow()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard currentProcess != nil else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "任务仍在进行"
        alert.informativeText = "退出会停止当前任务，已完成的文件会保留。"
        alert.addButton(withTitle: "继续任务")
        alert.addButton(withTitle: "停止并退出")
        guard alert.runModal() == .alertSecondButtonReturn else { return .terminateCancel }
        currentProcess?.terminate()
        currentProcess?.waitUntilExit()
        return .terminateNow
    }

    private func installMainMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(NSMenuItem(title: "退出 Video Downloader", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "编辑")
        for (title, action, key) in [("撤销", Selector(("undo:")), "z"), ("重做", Selector(("redo:")), "Z"),
                                    ("剪切", #selector(NSText.cut(_:)), "x"), ("复制", #selector(NSText.copy(_:)), "c"),
                                    ("粘贴", #selector(NSText.paste(_:)), "v"), ("全选", #selector(NSText.selectAll(_:)), "a")] {
            edit.addItem(NSMenuItem(title: title, action: action, keyEquivalent: key))
        }
        editItem.submenu = edit
        menu.addItem(editItem)
        NSApp.mainMenu = menu
    }

    private func label(_ text: String, size: CGFloat = 13, secondary: Bool = false) -> NSTextField {
        let field = NSTextField(labelWithString: text)
        field.font = .systemFont(ofSize: size)
        field.textColor = secondary ? .secondaryLabelColor : .labelColor
        field.lineBreakMode = .byTruncatingMiddle
        field.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return field
    }

    private func row(_ views: [NSView]) -> NSStackView {
        let stack = NSStackView(views: views)
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 10
        return stack
    }

    private func spacer() -> NSView {
        let view = NSView()
        view.setContentHuggingPriority(.defaultLow, for: .horizontal)
        return view
    }

    private func button(_ title: String, _ action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        return button
    }

    private func popup(_ titles: [String], name: String) -> NSPopUpButton {
        let popup = NSPopUpButton()
        popup.addItems(withTitles: titles)
        popup.setAccessibilityLabel(name)
        return popup
    }

    private func check(_ title: String) -> NSButton {
        NSButton(checkboxWithTitle: title, target: self, action: #selector(optionsChanged))
    }

    private func textScroll(editable: Bool, size: CGFloat) -> (NSScrollView, NSTextView) {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        scroll.translatesAutoresizingMaskIntoConstraints = false
        let text = NSTextView(frame: NSRect(x: 0, y: 0, width: 760, height: 60))
        text.isRichText = false
        text.isEditable = editable
        text.isSelectable = true
        text.isVerticallyResizable = true
        text.isHorizontallyResizable = false
        text.autoresizingMask = [.width]
        text.textContainer?.widthTracksTextView = true
        text.textContainerInset = NSSize(width: 8, height: 8)
        text.font = editable ? .systemFont(ofSize: size) : .monospacedSystemFont(ofSize: size, weight: .regular)
        text.textColor = .labelColor
        text.backgroundColor = .textBackgroundColor
        text.insertionPointColor = .controlAccentColor
        text.allowsUndo = editable
        scroll.documentView = text
        return (scroll, text)
    }

    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 850, height: 800),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Video Learning Downloader"
        window.minSize = NSSize(width: 790, height: 760)
        window.center()
        let content = window.contentView!
        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 10
        root.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 24),
            root.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24),
            root.topAnchor.constraint(equalTo: content.topAnchor, constant: 20),
            root.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -18)
        ])
        func add(_ view: NSView) {
            root.addArrangedSubview(view)
            view.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        }
        let heading = label("保存你需要的内容", size: 23)
        heading.font = .systemFont(ofSize: 23, weight: .semibold)
        clearButton = button("清空链接", #selector(clearForNextDownload))
        add(row([heading, spacer(), clearButton]))
        modeControl = NSSegmentedControl(labels: ["音频", "文字稿", "视频"], trackingMode: .selectOne,
                                         target: self, action: #selector(modeChanged))
        modeControl.segmentDistribution = .fillEqually
        modeControl.controlSize = .large
        modeControl.setAccessibilityLabel("保存模式")
        currentMode = UserDefaults.standard.string(forKey: "downloadMode") ?? "video"
        modeControl.selectedSegment = modes.firstIndex(of: currentMode) ?? 2
        currentMode = modes[modeControl.selectedSegment]
        add(modeControl)
        hintLabel = label("", secondary: true)
        add(hintLabel)
        add(label("视频链接 · 每行一个，同批使用当前模式", secondary: true))
        let (urlScroll, urlText) = textScroll(editable: true, size: 14)
        urlTextView = urlText
        urlTextView.setAccessibilityLabel("视频链接")
        urlScroll.heightAnchor.constraint(equalToConstant: 70).isActive = true
        add(urlScroll)

        qualityPopup = popup(["1080p", "720p", "480p", "最高可用"], name: "视频清晰度")
        audioPopup = popup(["高音质 · VBR", "标准 · 192 kbps", "小体积 · 128 kbps"], name: "MP3 音质")
        languagePopup = popup(["自动 · 中英文", "中文优先", "英文优先"], name: "字幕语言")
        coverCheck = check("保存封面")
        transcriptCheck = check("附带文字稿")
        subtitleCheck = check("保留原始字幕")
        timestampCheck = check("保留时间戳")
        qualityRow = row([label("清晰度"), qualityPopup])
        audioRow = row([label("MP3 音质"), audioPopup])
        optionRow = row([qualityRow, audioRow, coverCheck, transcriptCheck, subtitleCheck, spacer()])
        add(optionRow)
        languageRow = row([label("字幕语言"), languagePopup, timestampCheck, spacer()])
        add(languageRow)
        guestField = NSTextField()
        guestField.placeholderString = "填写已确认姓名；留空归入“待确认受访者”"
        guestField.setAccessibilityLabel("受访者姓名")
        guestField.setContentHuggingPriority(.defaultLow, for: .horizontal)
        guestRow = row([label("受访者"), guestField])
        add(guestRow)
        transcriptPathLabel = label("", secondary: true)
        add(transcriptPathLabel)

        outputField = NSTextField()
        outputField.setAccessibilityLabel("保存目录")
        chooseButton = button("选择…", #selector(chooseFolder))
        add(row([label("保存到", secondary: true), outputField, chooseButton]))
        outputField.setContentHuggingPriority(.defaultLow, for: .horizontal)

        titleLabel = label("等待开始", size: 14)
        titleLabel.font = .systemFont(ofSize: 14, weight: .medium)
        add(titleLabel)
        progress = NSProgressIndicator()
        progress.style = .bar
        progress.isIndeterminate = false
        progress.minValue = 0
        progress.maxValue = 100
        progress.setAccessibilityLabel("当前阶段进度")
        add(progress)
        detailLabel = label("选择模式并粘贴链接后即可开始。", secondary: true)
        add(detailLabel)
        add(label("本次结果", secondary: true))
        let resultsScroll = NSScrollView()
        resultsScroll.contentView = TopClipView()
        resultsScroll.hasVerticalScroller = true
        resultsScroll.drawsBackground = false
        resultsScroll.translatesAutoresizingMaskIntoConstraints = false
        resultsScroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 80).isActive = true
        resultStack = NSStackView()
        resultStack.orientation = .vertical
        resultStack.alignment = .leading
        resultStack.spacing = 10
        resultStack.edgeInsets = NSEdgeInsets(top: 4, left: 0, bottom: 8, right: 8)
        resultStack.translatesAutoresizingMaskIntoConstraints = false
        resultsScroll.documentView = resultStack
        resultStack.widthAnchor.constraint(equalTo: resultsScroll.contentView.widthAnchor).isActive = true
        add(resultsScroll)
        resetResults()
        logsButton = button("显示详细日志", #selector(toggleLogs))
        add(row([logsButton, spacer()]))
        let (scroll, text) = textScroll(editable: false, size: 11)
        logScroll = scroll
        logTextView = text
        logScroll.heightAnchor.constraint(equalToConstant: 120).isActive = true
        logScroll.isHidden = true
        add(logScroll)
        statusLabel = label("准备就绪", secondary: true)
        stopButton = button("停止", #selector(stopDownload))
        stopButton.isEnabled = false
        downloadButton = button("下载视频", #selector(startDownload))
        downloadButton.keyEquivalent = "\r"
        add(row([statusLabel, spacer(), stopButton, downloadButton]))
        loadModePreferences()
        updateModeUI()
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(urlTextView)
    }

    private func key(_ suffix: String) -> String { "mode.\(currentMode).\(suffix)" }

    private func saveModePreferences() {
        let defaults = UserDefaults.standard
        defaults.set(outputField.stringValue, forKey: key("output"))
        defaults.set(coverCheck.state == .on, forKey: key("cover"))
        defaults.set(transcriptCheck.state == .on, forKey: key("transcript"))
        defaults.set(subtitleCheck.state == .on, forKey: key("subtitles"))
        defaults.set(timestampCheck.state == .on, forKey: key("timestamps"))
        defaults.set(qualityPopup.indexOfSelectedItem, forKey: key("quality"))
        defaults.set(audioPopup.indexOfSelectedItem, forKey: key("audio"))
        defaults.set(languagePopup.indexOfSelectedItem, forKey: key("language"))
    }

    private func loadModePreferences() {
        let defaults = UserDefaults.standard
        let defaultFolder = currentMode == "audio" ? NSHomeDirectory() + "/Music" : currentMode == "text" ? "/Volumes/xssd/Movies/文字稿" : defaults.string(forKey: "outputPath") ?? defaultOutputPath
        outputField.stringValue = defaults.string(forKey: key("output")) ?? defaultFolder
        func state(_ name: String, fallback: Bool) -> NSControl.StateValue {
            (defaults.object(forKey: key(name)) as? Bool ?? fallback) ? .on : .off
        }
        coverCheck.state = state("cover", fallback: currentMode == "video")
        transcriptCheck.state = state("transcript", fallback: false)
        subtitleCheck.state = state("subtitles", fallback: false)
        timestampCheck.state = state("timestamps", fallback: true)
        qualityPopup.selectItem(at: min(3, max(0, defaults.integer(forKey: key("quality")))))
        audioPopup.selectItem(at: min(2, max(0, defaults.integer(forKey: key("audio")))))
        languagePopup.selectItem(at: min(2, max(0, defaults.integer(forKey: key("language")))))
    }

    @objc private func modeChanged() {
        saveModePreferences()
        currentMode = modes[modeControl.selectedSegment]
        UserDefaults.standard.set(currentMode, forKey: "downloadMode")
        loadModePreferences()
        updateModeUI()
    }

    @objc private func optionsChanged() { updateModeUI(); saveModePreferences() }

    private func updateModeUI() {
        let text = currentMode == "text"
        qualityRow.isHidden = currentMode != "video"
        audioRow.isHidden = currentMode != "audio"
        coverCheck.isHidden = text
        transcriptCheck.isHidden = text
        subtitleCheck.isHidden = currentMode != "video"
        optionRow.isHidden = text
        languageRow.isHidden = !text && transcriptCheck.state != .on && (currentMode != "video" || subtitleCheck.state != .on)
        timestampCheck.isHidden = !text && transcriptCheck.state != .on
        guestRow.isHidden = languageRow.isHidden
        transcriptPathLabel.isHidden = text || languageRow.isHidden
        transcriptPathLabel.stringValue = "文字稿／字幕保存到：\(transcriptOutputPath)（可在文字稿模式中修改）"
        downloadButton.title = currentMode == "audio" ? "提取音频" : text ? "获取文字稿" : "下载视频"
        hintLabel.stringValue = currentMode == "audio" ? "保存 MP3，适合听播客与课程。可附带封面和文字稿。" : text ? "从平台字幕生成 Markdown + TXT；无可用字幕时会提示，暂不支持语音转写。" : "保存 MP4，可附带封面、平台字幕或文字稿。"
    }

    private var transcriptOutputPath: String {
        UserDefaults.standard.string(forKey: "mode.text.output") ?? "/Volumes/xssd/Movies/文字稿"
    }

    @objc private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: outputField.stringValue.expandingTildeInPath)
        if panel.runModal() == .OK, let url = panel.url {
            outputField.stringValue = url.path
            saveModePreferences()
        }
    }

    @objc private func toggleLogs() {
        logScroll.isHidden.toggle()
        logsButton.title = logScroll.isHidden ? "显示详细日志" : "隐藏详细日志"
    }

    private func resetResults() {
        for view in resultStack.arrangedSubviews { resultStack.removeArrangedSubview(view); view.removeFromSuperview() }
        resultCount = 0
        resultStack.addArrangedSubview(label("完成的文件会显示在这里，可以直接打开或在 Finder 中查看。", secondary: true))
    }

    @objc private func clearForNextDownload() {
        guard currentProcess == nil else { return }
        urlTextView.string = ""
        window.makeFirstResponder(urlTextView)
    }

    @objc private func startDownload() {
        guard currentProcess == nil else { return }
        let urls = urlTextView.string.split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        guard !urls.isEmpty, urls.allSatisfy({ value in
            guard let url = URL(string: value), let scheme = url.scheme else { return false }
            return ["http", "https"].contains(scheme) && url.host != nil
        }) else { showAlert("请粘贴有效的 http 或 https 视频链接，每行一个。"); return }
        let output = outputField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).expandingTildeInPath
        guard !output.isEmpty else { showAlert("请先选择保存目录。"); return }
        guard let resource = Bundle.main.resourceURL else { showAlert("找不到应用资源。"); return }
        let bundled = resource.appendingPathComponent("scripts/desktop-task.py")
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("scripts/desktop-task.py")
        let script = FileManager.default.fileExists(atPath: bundled.path) ? bundled : source
        guard FileManager.default.fileExists(atPath: script.path) else { showAlert("找不到任务脚本，请重新安装应用。"); return }
        saveModePreferences()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        var arguments = ["python3", "-B", "-u", script.path, "--mode", currentMode, "--output-dir", output,
                         "--transcript-dir", transcriptOutputPath,
                         "--guest", guestField.stringValue,
                         "--quality", ["1080", "720", "480", "best"][qualityPopup.indexOfSelectedItem],
                         "--audio-quality", ["0", "192K", "128K"][audioPopup.indexOfSelectedItem],
                         "--language", ["auto", "zh", "en"][languagePopup.indexOfSelectedItem]]
        if currentMode != "text" && coverCheck.state == .on { arguments.append("--cover") }
        if currentMode != "text" && transcriptCheck.state == .on { arguments.append("--transcript") }
        if currentMode == "video" && subtitleCheck.state == .on { arguments.append("--subtitles") }
        if timestampCheck.state == .on { arguments.append("--timestamps") }
        arguments.append(contentsOf: urls)
        process.arguments = arguments
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = "\(NSHomeDirectory())/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + (environment["PATH"] ?? "")
        environment["PYTHONIOENCODING"] = "utf-8"
        process.environment = environment
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        resetResults()
        logTextView.string = ""
        outputBuffer = Data()
        receivedDone = false
        titleLabel.stringValue = "正在准备任务…"
        statusLabel.stringValue = "处理中"
        setStage("正在读取链接…")
        setRunning(true)
        currentProcess = process
        do {
            try process.run()
            // One reader owns the pipe. It drains every byte before reporting exit.
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                while true {
                    let data = pipe.fileHandleForReading.availableData
                    if data.isEmpty { break }
                    DispatchQueue.main.async { self?.consume(data) }
                }
                process.waitUntilExit()
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    if !self.outputBuffer.isEmpty {
                        self.handleLine(String(decoding: self.outputBuffer, as: UTF8.self))
                        self.outputBuffer.removeAll()
                    }
                    self.progress.stopAnimation(nil)
                    self.progress.isIndeterminate = false
                    if !self.receivedDone {
                        self.statusLabel.stringValue = "任务失败"
                        self.detailLabel.stringValue = "任务意外结束（退出码 \(process.terminationStatus)），请展开详细日志。"
                    }
                    self.currentProcess = nil
                    self.setRunning(false)
                }
            }
        } catch {
            currentProcess = nil
            progress.stopAnimation(nil)
            progress.isIndeterminate = false
            setRunning(false)
            statusLabel.stringValue = "启动失败"
            detailLabel.stringValue = error.localizedDescription
        }
    }

    private func consume(_ data: Data) {
        outputBuffer.append(data)
        while let newline = outputBuffer.firstIndex(of: 10) {
            let line = String(decoding: outputBuffer[..<newline], as: UTF8.self)
            outputBuffer.removeSubrange(...newline)
            handleLine(line)
        }
    }

    private func setStage(_ text: String) {
        detailLabel.stringValue = text
        progress.isIndeterminate = true
        progress.startAnimation(nil)
    }

    private func handleLine(_ line: String) {
        guard let data = line.data(using: .utf8), let event = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let type = event["event"] as? String else { appendLog(line); return }
        let text = event["text"] as? String ?? ""
        switch type {
        case "item":
            itemPrefix = "\(event["index"] ?? 1)/\(event["total"] ?? 1)"
            titleLabel.stringValue = "\(itemPrefix) · \(text)"
            appendLog("\n\(titleLabel.stringValue)")
        case "title": titleLabel.stringValue = "\(itemPrefix) · \(text)"
        case "stage": setStage(text)
        case "progress":
            progress.stopAnimation(nil)
            progress.isIndeterminate = false
            progress.doubleValue = event["percent"] as? Double ?? 0
            detailLabel.stringValue = "当前文件：\(text)"
        case "result": addResult(event)
        case "done":
            receivedDone = true
            progress.stopAnimation(nil)
            progress.isIndeterminate = false
            let status = event["status"] as? String ?? "failed"
            if status == "complete" { progress.doubleValue = 100 }
            statusLabel.stringValue = ["complete": "已完成", "partial": "部分完成", "failed": "未完成", "cancelled": "已停止"][status] ?? "已结束"
            detailLabel.stringValue = text
            appendLog(text)
        default: appendLog(text)
        }
    }

    private func addResult(_ event: [String: Any]) {
        if resultCount == 0 {
            for view in resultStack.arrangedSubviews { resultStack.removeArrangedSubview(view); view.removeFromSuperview() }
        }
        resultCount += 1
        let kind = event["kind"] as? String ?? "文件"
        let success = event["status"] as? String == "complete"
        let message = event["message"] as? String ?? ""
        let heading = label("\(itemPrefix) · \(kind) · \(success ? "已完成" : "未完成")", size: 13)
        heading.font = .systemFont(ofSize: 13, weight: .semibold)
        heading.textColor = success ? .labelColor : .systemOrange
        let description = NSTextField(wrappingLabelWithString: message)
        description.font = .systemFont(ofSize: 12)
        description.textColor = .secondaryLabelColor
        description.isSelectable = true
        let paths = event["paths"] as? [String] ?? []
        let buttons = row([heading, spacer()])
        if let first = paths.first {
            let url = URL(fileURLWithPath: first)
            func action(_ title: String, _ selector: Selector, _ target: URL) {
                let button = ArtifactButton(title: title, target: self, action: selector)
                button.fileURL = target
                button.bezelStyle = .rounded
                button.toolTip = target.path
                buttons.addArrangedSubview(button)
            }
            if kind == "文字稿", let txt = paths.first(where: { $0.hasSuffix(".txt") }) {
                action("预览", #selector(previewArtifact(_:)), URL(fileURLWithPath: txt))
                action("复制", #selector(copyArtifact(_:)), URL(fileURLWithPath: txt))
            } else {
                action("打开", #selector(openArtifact(_:)), url)
            }
            action("Finder", #selector(revealArtifact(_:)), url)
        }
        let card = NSStackView(views: [buttons, description])
        card.orientation = .vertical
        card.alignment = .leading
        card.spacing = 4
        resultStack.addArrangedSubview(card)
        card.widthAnchor.constraint(equalTo: resultStack.widthAnchor, constant: -8).isActive = true
        buttons.widthAnchor.constraint(equalTo: card.widthAnchor).isActive = true
        description.widthAnchor.constraint(equalTo: card.widthAnchor).isActive = true
        appendLog("\(kind)：\(message)\n" + paths.joined(separator: "\n"))
    }

    @objc private func openArtifact(_ sender: ArtifactButton) {
        if let url = sender.fileURL { NSWorkspace.shared.open(url) }
    }
    @objc private func revealArtifact(_ sender: ArtifactButton) {
        if let url = sender.fileURL { NSWorkspace.shared.activateFileViewerSelecting([url]) }
    }
    @objc private func copyArtifact(_ sender: ArtifactButton) {
        guard let url = sender.fileURL, let text = try? String(contentsOf: url, encoding: .utf8) else { showAlert("文字稿文件已移动或无法读取。"); return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        statusLabel.stringValue = "文字稿已复制"
    }
    @objc private func previewArtifact(_ sender: ArtifactButton) {
        guard let url = sender.fileURL, let text = try? String(contentsOf: url, encoding: .utf8) else { showAlert("文字稿文件已移动或无法读取。"); return }
        previewWindow?.close()
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 680, height: 520),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        panel.isReleasedWhenClosed = false
        panel.title = "文字稿预览 · \(url.lastPathComponent)"
        let (scroll, view) = textScroll(editable: false, size: 14)
        view.font = .systemFont(ofSize: 14)
        view.string = text
        panel.contentView = scroll
        previewWindow = panel
        panel.center()
        panel.makeKeyAndOrderFront(nil)
    }

    @objc private func stopDownload() {
        guard let process = currentProcess, process.isRunning else { return }
        stopButton.isEnabled = false
        statusLabel.stringValue = "正在停止…"
        process.terminate()
    }

    private func setRunning(_ running: Bool) {
        downloadButton.isEnabled = !running
        stopButton.isEnabled = running
        clearButton.isEnabled = !running
        modeControl.isEnabled = !running
        outputField.isEnabled = !running
        urlTextView.isEditable = !running
        chooseButton.isEnabled = !running
        guestField.isEnabled = !running
        for control in [qualityPopup, audioPopup, languagePopup] { control?.isEnabled = !running }
        for control in [coverCheck, transcriptCheck, subtitleCheck, timestampCheck] { control?.isEnabled = !running }
    }

    private func appendLog(_ text: String) {
        let attributes: [NSAttributedString.Key: Any] = [.foregroundColor: NSColor.labelColor,
            .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)]
        logTextView.textStorage?.append(NSAttributedString(string: text + "\n", attributes: attributes))
        if let storage = logTextView.textStorage, storage.length > 200_000 {
            storage.deleteCharacters(in: NSRange(location: 0, length: storage.length - 160_000))
        }
        logTextView.scrollToEndOfDocument(nil)
    }

    private func showAlert(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Video Downloader"
        alert.informativeText = message
        alert.runModal()
    }
}
