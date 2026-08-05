import AppKit
import CFNetwork
import Foundation

extension String {
    var expandingTildeInPath: String {
        (self as NSString).expandingTildeInPath
    }
}

private func loadApplicationIcon() -> NSImage? {
    guard let iconURL = Bundle.main.url(forResource: "AppIcon", withExtension: "icns") else {
        return nil
    }
    return NSImage(contentsOf: iconURL)
}

@main
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var urlTextView: NSTextView!
    private var logTextView: NSTextView!
    private var outputField: NSTextField!
    private var qualityPopup: NSPopUpButton!
    private var statusLabel: NSTextField!
    private var downloadButton: NSButton!
    private var stopButton: NSButton!
    private var clearButton: NSButton!
    private var currentProcess: Process?

    private let defaultOutputPath = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Movies").path

    static func main() {
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.regular)
        if let icon = loadApplicationIcon() {
            application.applicationIconImage = icon
        }
        _ = NSApplicationMain(CommandLine.argc, CommandLine.unsafeArgv)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        installApplicationIcon()
        installMainMenu()
        buildWindow()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    private func installApplicationIcon() {
        guard let icon = loadApplicationIcon() else {
            return
        }
        NSApp.applicationIconImage = icon
    }

    private func buildWindow() {
        let contentView = NSView()
        contentView.translatesAutoresizingMaskIntoConstraints = false

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 820, height: 620),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Video Learning Downloader"
        window.center()
        window.contentView = contentView

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 14
        root.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(root)

        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 22),
            root.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -22),
            root.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 22),
            root.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -18)
        ])

        root.addArrangedSubview(makeHeader())
        root.addArrangedSubview(label("视频链接"))
        root.addArrangedSubview(makeURLInput())
        root.addArrangedSubview(makePathRow())
        root.addArrangedSubview(label("下载日志"))
        root.addArrangedSubview(makeLogView())
        root.addArrangedSubview(makeFooter())

        appendLog("准备就绪。粘贴链接，选择保存文件夹，然后点击下载。\n")
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(urlTextView)
    }

    private func installMainMenu() {
        let mainMenu = NSMenu()

        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenu.addItem(
            NSMenuItem(
                title: "退出 Video Downloader",
                action: #selector(NSApplication.terminate(_:)),
                keyEquivalent: "q"
            )
        )
        appMenuItem.submenu = appMenu

        let editMenuItem = NSMenuItem()
        mainMenu.addItem(editMenuItem)
        let editMenu = NSMenu(title: "编辑")
        editMenu.addItem(NSMenuItem(title: "撤销", action: Selector(("undo:")), keyEquivalent: "z"))
        editMenu.addItem(NSMenuItem(title: "重做", action: Selector(("redo:")), keyEquivalent: "Z"))
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(NSMenuItem(title: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x"))
        editMenu.addItem(NSMenuItem(title: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c"))
        editMenu.addItem(NSMenuItem(title: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v"))
        editMenu.addItem(NSMenuItem(title: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a"))
        editMenuItem.submenu = editMenu

        NSApp.mainMenu = mainMenu
    }

    private func makeHeader() -> NSView {
        let container = NSView()
        container.translatesAutoresizingMaskIntoConstraints = false

        let title = NSTextField(labelWithString: "视频下载")
        title.font = .systemFont(ofSize: 24, weight: .bold)
        title.translatesAutoresizingMaskIntoConstraints = false

        clearButton = NSButton(title: "清空链接", target: self, action: #selector(clearForNextDownload))
        clearButton.bezelStyle = .rounded
        clearButton.controlSize = .large
        clearButton.font = .systemFont(ofSize: 14, weight: .semibold)
        clearButton.translatesAutoresizingMaskIntoConstraints = false

        let qualityLabel = NSTextField(labelWithString: "清晰度")
        qualityLabel.textColor = .secondaryLabelColor

        qualityPopup = NSPopUpButton()
        qualityPopup.addItems(withTitles: ["1080", "720", "480", "best"])
        qualityPopup.selectItem(withTitle: UserDefaults.standard.string(forKey: "quality") ?? "1080")

        let qualityControls = NSStackView(views: [qualityLabel, qualityPopup])
        qualityControls.orientation = .horizontal
        qualityControls.alignment = .centerY
        qualityControls.spacing = 10
        qualityControls.translatesAutoresizingMaskIntoConstraints = false

        container.addSubview(title)
        container.addSubview(clearButton)
        container.addSubview(qualityControls)

        NSLayoutConstraint.activate([
            container.widthAnchor.constraint(greaterThanOrEqualToConstant: 760),
            container.heightAnchor.constraint(greaterThanOrEqualToConstant: 38),
            title.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            title.centerYAnchor.constraint(equalTo: container.centerYAnchor),
            clearButton.centerXAnchor.constraint(equalTo: container.centerXAnchor),
            clearButton.centerYAnchor.constraint(equalTo: container.centerYAnchor),
            clearButton.widthAnchor.constraint(greaterThanOrEqualToConstant: 116),
            clearButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 34),
            qualityControls.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            qualityControls.centerYAnchor.constraint(equalTo: container.centerYAnchor)
        ])
        return container
    }

    private func makeURLInput() -> NSView {
        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.borderType = .bezelBorder
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        urlTextView = NSTextView()
        urlTextView.isRichText = false
        urlTextView.font = .systemFont(ofSize: 14)
        urlTextView.textColor = .labelColor
        urlTextView.backgroundColor = .textBackgroundColor
        urlTextView.insertionPointColor = .controlAccentColor
        urlTextView.allowsUndo = true
        urlTextView.string = ""
        scrollView.documentView = urlTextView

        NSLayoutConstraint.activate([
            scrollView.heightAnchor.constraint(equalToConstant: 120),
            scrollView.widthAnchor.constraint(greaterThanOrEqualToConstant: 760)
        ])
        return scrollView
    }

    private func makePathRow() -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10
        row.translatesAutoresizingMaskIntoConstraints = false

        let pathLabel = NSTextField(labelWithString: "保存到")
        pathLabel.textColor = .secondaryLabelColor

        outputField = NSTextField()
        outputField.stringValue = UserDefaults.standard.string(forKey: "outputPath") ?? defaultOutputPath

        let chooseButton = NSButton(title: "选择", target: self, action: #selector(chooseFolder))
        chooseButton.bezelStyle = .rounded

        row.addArrangedSubview(pathLabel)
        row.addArrangedSubview(outputField)
        row.addArrangedSubview(chooseButton)
        outputField.widthAnchor.constraint(greaterThanOrEqualToConstant: 560).isActive = true
        row.widthAnchor.constraint(greaterThanOrEqualToConstant: 760).isActive = true
        return row
    }

    private func makeLogView() -> NSView {
        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.borderType = .bezelBorder
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        logTextView = NSTextView()
        logTextView.isEditable = false
        logTextView.isRichText = false
        logTextView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        logTextView.textColor = .labelColor
        logTextView.backgroundColor = .textBackgroundColor
        logTextView.string = ""
        scrollView.documentView = logTextView

        NSLayoutConstraint.activate([
            scrollView.heightAnchor.constraint(greaterThanOrEqualToConstant: 260),
            scrollView.widthAnchor.constraint(greaterThanOrEqualToConstant: 760)
        ])
        return scrollView
    }

    private func makeFooter() -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10
        row.translatesAutoresizingMaskIntoConstraints = false

        statusLabel = NSTextField(labelWithString: "准备就绪")
        statusLabel.textColor = .secondaryLabelColor

        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)

        stopButton = NSButton(title: "停止", target: self, action: #selector(stopDownload))
        stopButton.bezelStyle = .rounded
        stopButton.isEnabled = false

        downloadButton = NSButton(title: "下载", target: self, action: #selector(startDownload))
        downloadButton.bezelStyle = .rounded
        downloadButton.keyEquivalent = "\r"

        row.addArrangedSubview(statusLabel)
        row.addArrangedSubview(spacer)
        row.addArrangedSubview(stopButton)
        row.addArrangedSubview(downloadButton)
        row.widthAnchor.constraint(greaterThanOrEqualToConstant: 760).isActive = true
        return row
    }

    private func label(_ value: String) -> NSTextField {
        let text = NSTextField(labelWithString: value)
        text.textColor = .secondaryLabelColor
        text.font = .systemFont(ofSize: 13, weight: .medium)
        return text
    }

    @objc private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: outputField.stringValue.expandingTildeInPath)

        if panel.runModal() == .OK, let url = panel.url {
            outputField.stringValue = url.path
            UserDefaults.standard.set(url.path, forKey: "outputPath")
        }
    }

    @objc private func startDownload() {
        let urls = urlTextView.string
            .split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        guard !urls.isEmpty else {
            showAlert("先粘贴视频链接。")
            return
        }

        let outputPath = outputField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines).expandingTildeInPath
        guard !outputPath.isEmpty else {
            showAlert("先选择保存文件夹。")
            return
        }

        do {
            try FileManager.default.createDirectory(atPath: outputPath, withIntermediateDirectories: true)
        } catch {
            showAlert("保存文件夹创建失败：\(error.localizedDescription)")
            return
        }

        UserDefaults.standard.set(outputPath, forKey: "outputPath")
        UserDefaults.standard.set(qualityPopup.titleOfSelectedItem ?? "1080", forKey: "quality")

        clearLog()
        appendLog("保存到: \(outputPath)\n")
        setRunning(true)

        let process = Process()
        let pipe = Pipe()
        let manifestURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("video-learning-downloader-\(UUID().uuidString).txt")
        let ytdlp = executablePath(named: "yt-dlp", preferred: "~/.local/bin/yt-dlp")
        let proxyURL = systemProxyURL()
        let nodePath = nodeExecutablePath()
        let quality = qualityPopup.titleOfSelectedItem ?? "1080"
        let format: String
        if quality == "best" {
            format = "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/best"
        } else {
            format = "bv*[height<=\(quality)][ext=mp4]+ba[ext=m4a]/bv*[height<=\(quality)]+ba/b[height<=\(quality)]/best"
        }

        process.executableURL = URL(fileURLWithPath: ytdlp.executable)
        var arguments = [
            "--newline",
            "--no-playlist",
            "--restrict-filenames",
            "--trim-filenames", "160",
            "--merge-output-format", "mp4",
            "--embed-metadata",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--print-to-file", "after_move:%(filepath)s", manifestURL.path,
            "--ffmpeg-location", "~/.local/bin".expandingTildeInPath
        ]

        if let proxyURL {
            arguments += ["--proxy", proxyURL]
            appendLog("系统代理: \(proxyURL)\n")
        } else {
            appendLog("系统代理: 未启用\n")
        }

        if let nodePath {
            arguments += ["--js-runtimes", "node:\(nodePath)"]
            appendLog("JavaScript 运行时: Node \(nodePath)\n")
        } else {
            appendLog("提示: 未找到 Node，部分 YouTube 格式可能不可用。\n")
        }

        arguments += [
            "-f", format,
            "-o", "\(outputPath)/%(extractor)s/%(uploader|unknown)s/%(upload_date>%Y-%m-%d|unknown)s_%(title).120B_%(id)s.%(ext)s"
        ] + urls
        process.arguments = ytdlp.prefixArguments + arguments
        process.standardOutput = pipe
        process.standardError = pipe
        process.environment = environmentWithLocalBin(nodePath: nodePath)

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async {
                self?.appendLog(text)
            }
        }

        process.terminationHandler = { [weak self] finishedProcess in
            pipe.fileHandleForReading.readabilityHandler = nil
            DispatchQueue.main.async {
                let ok = finishedProcess.terminationStatus == 0
                let downloadedFiles = self?.downloadedFiles(from: manifestURL) ?? []
                try? FileManager.default.removeItem(at: manifestURL)

                if ok {
                    self?.appendDownloadSummary(videoPaths: downloadedFiles)
                    self?.statusLabel.stringValue = "下载完成：\(downloadedFiles.count) 个视频"
                } else {
                    self?.appendLog("\n下载结束，退出码: \(finishedProcess.terminationStatus)\n")
                    self?.statusLabel.stringValue = "下载失败"
                }
                self?.currentProcess = nil
                self?.setRunning(false)
            }
        }

        do {
            currentProcess = process
            try process.run()
            statusLabel.stringValue = "下载中..."
        } catch {
            try? FileManager.default.removeItem(at: manifestURL)
            currentProcess = nil
            setRunning(false)
            showAlert("启动 yt-dlp 失败：\(error.localizedDescription)")
        }
    }

    @objc private func clearForNextDownload() {
        guard currentProcess == nil else { return }
        urlTextView.string = ""
        outputField.stringValue = defaultOutputPath
        UserDefaults.standard.set(defaultOutputPath, forKey: "outputPath")
        statusLabel.stringValue = "准备就绪"
        appendLog("\n已清空链接，保存目录已恢复为：\(defaultOutputPath)\n")
        window.makeFirstResponder(urlTextView)
    }

    @objc private func stopDownload() {
        currentProcess?.terminate()
        appendLog("\n已请求停止。\n")
        statusLabel.stringValue = "已停止"
        setRunning(false)
    }

    private func setRunning(_ running: Bool) {
        downloadButton.isEnabled = !running
        stopButton.isEnabled = running
        clearButton.isEnabled = !running
    }

    private func downloadedFiles(from manifestURL: URL) -> [String] {
        guard let contents = try? String(contentsOf: manifestURL, encoding: .utf8) else {
            return []
        }
        return contents
            .split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func appendDownloadSummary(videoPaths: [String]) {
        appendLog("\n下载完成。本次内容：\n")

        if videoPaths.isEmpty {
            appendLog("视频已下载，但未读取到最终文件名。\n")
            return
        }

        for path in videoPaths {
            let videoURL = URL(fileURLWithPath: path)
            appendLog("视频：\(videoURL.lastPathComponent)\n")

            let coverURL = videoURL.deletingPathExtension().appendingPathExtension("jpg")
            if FileManager.default.fileExists(atPath: coverURL.path) {
                appendLog("封面：\(coverURL.lastPathComponent)\n")
            }
            appendLog("位置：\(videoURL.deletingLastPathComponent().path)\n")
        }
    }

    private func appendLog(_ text: String) {
        guard let storage = logTextView.textStorage else { return }
        let attributes: [NSAttributedString.Key: Any] = [
            .foregroundColor: NSColor.labelColor,
            .font: logTextView.font ?? NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        ]
        storage.append(NSAttributedString(string: text, attributes: attributes))
        logTextView.scrollToEndOfDocument(nil)
    }

    private func clearLog() {
        logTextView.string = ""
    }

    private func showAlert(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Video Downloader"
        alert.informativeText = message
        alert.alertStyle = .informational
        alert.runModal()
    }

    private func executablePath(named name: String, preferred: String) -> (executable: String, prefixArguments: [String]) {
        let preferredPath = preferred.expandingTildeInPath
        if FileManager.default.isExecutableFile(atPath: preferredPath) {
            return (preferredPath, [])
        }
        return ("/usr/bin/env", [name])
    }

    private func systemProxyURL() -> String? {
        guard let settings = CFNetworkCopySystemProxySettings()?.takeRetainedValue() as? [String: Any] else {
            return nil
        }

        func isEnabled(_ key: CFString) -> Bool {
            (settings[key as String] as? NSNumber)?.boolValue == true
        }

        func proxyURL(hostKey: CFString, portKey: CFString, scheme: String) -> String? {
            guard
                let host = settings[hostKey as String] as? String,
                !host.isEmpty,
                let port = settings[portKey as String] as? NSNumber
            else {
                return nil
            }
            return "\(scheme)://\(host):\(port.intValue)"
        }

        if isEnabled(kCFNetworkProxiesHTTPSEnable),
           let proxy = proxyURL(
               hostKey: kCFNetworkProxiesHTTPSProxy,
               portKey: kCFNetworkProxiesHTTPSPort,
               scheme: "http"
           ) {
            return proxy
        }

        if isEnabled(kCFNetworkProxiesHTTPEnable),
           let proxy = proxyURL(
               hostKey: kCFNetworkProxiesHTTPProxy,
               portKey: kCFNetworkProxiesHTTPPort,
               scheme: "http"
           ) {
            return proxy
        }

        if isEnabled(kCFNetworkProxiesSOCKSEnable),
           let proxy = proxyURL(
               hostKey: kCFNetworkProxiesSOCKSProxy,
               portKey: kCFNetworkProxiesSOCKSPort,
               scheme: "socks5h"
           ) {
            return proxy
        }

        return nil
    }

    private func nodeExecutablePath() -> String? {
        let home = FileManager.default.homeDirectoryForCurrentUser
        var candidates = [
            home.appendingPathComponent(".local/bin/node").path,
            "/opt/homebrew/bin/node",
            "/usr/local/bin/node",
            "/usr/bin/node"
        ]

        let piNodeRoot = home.appendingPathComponent(".local/share/pi-node")
        if let installs = try? FileManager.default.contentsOfDirectory(
            at: piNodeRoot,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ) {
            let piNodeCandidates = installs
                .filter { $0.lastPathComponent.hasPrefix("node-") }
                .sorted { $0.lastPathComponent > $1.lastPathComponent }
                .map { $0.appendingPathComponent("bin/node").path }
            candidates.insert(contentsOf: piNodeCandidates, at: 0)
        }

        if let path = ProcessInfo.processInfo.environment["PATH"] {
            candidates += path.split(separator: ":").map { "\($0)/node" }
        }

        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private func environmentWithLocalBin(nodePath: String?) -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        var extraPaths = [
            "~/.local/bin".expandingTildeInPath,
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin"
        ]
        if let nodePath {
            extraPaths.insert(URL(fileURLWithPath: nodePath).deletingLastPathComponent().path, at: 0)
        }
        environment["PATH"] = "\(extraPaths.joined(separator: ":")):\(environment["PATH"] ?? "")"
        return environment
    }
}
