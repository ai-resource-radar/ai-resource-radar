import AppKit
import Foundation

final class RadarMenu: NSObject, NSApplicationDelegate, NSUserNotificationCenterDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let menu = NSMenu()
    private let stateItem = NSMenuItem(title: "正在连接本地雷达…", action: nil, keyEquivalent: "")
    private let baseURL = URL(string: "http://127.0.0.1:18766")!
    private var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem.button?.title = "AI 雷达"
        stateItem.isEnabled = false
        menu.addItem(stateItem)
        let open = NSMenuItem(title: "打开 AI 资源雷达", action: #selector(openRadar), keyEquivalent: "")
        open.target = self
        menu.addItem(open)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "退出菜单栏", action: #selector(quitApp), keyEquivalent: "")
        quit.target = self
        menu.addItem(quit)
        statusItem.menu = menu
        NSUserNotificationCenter.default.delegate = self
        refresh()
        timer = Timer.scheduledTimer(
            timeInterval: 60,
            target: self,
            selector: #selector(refresh),
            userInfo: nil,
            repeats: true
        )
    }

    @objc private func refresh() {
        let url = baseURL.appendingPathComponent("api/ai-resources/notifications/pending")
        URLSession.shared.dataTask(with: url) { data, _, error in
            guard error == nil, let data,
                  let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let notifications = payload["notifications"] as? [[String: Any]]
            else {
                DispatchQueue.main.async { self.stateItem.title = "本地雷达未连接" }
                return
            }
            DispatchQueue.main.async {
                self.stateItem.title = notifications.isEmpty
                    ? "暂无新提醒"
                    : "\(notifications.count) 条新提醒"
                notifications.forEach { self.deliver($0) }
            }
        }.resume()
    }

    private func deliver(_ payload: [String: Any]) {
        guard let id = payload["id"] as? Int,
              let title = payload["title"] as? String,
              let body = payload["body"] as? String,
              let target = payload["target_url"] as? String else { return }
        let notice = NSUserNotification()
        notice.identifier = "ai-resource-radar-\(id)"
        notice.title = title
        notice.informativeText = body
        notice.hasActionButton = true
        notice.actionButtonTitle = "查看"
        notice.userInfo = ["notification_id": id, "target_url": target]
        NSUserNotificationCenter.default.deliver(notice)
        update(id: id, status: "delivered")
    }

    private func update(id: Int, status: String) {
        let url = baseURL
            .appendingPathComponent("api/ai-resources/notifications")
            .appendingPathComponent(String(id))
            .appendingPathComponent(status)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        URLSession.shared.dataTask(with: request).resume()
    }

    func userNotificationCenter(
        _ center: NSUserNotificationCenter,
        shouldPresent notification: NSUserNotification
    ) -> Bool { true }

    func userNotificationCenter(
        _ center: NSUserNotificationCenter,
        didActivate notification: NSUserNotification
    ) {
        guard let info = notification.userInfo,
              let id = info["notification_id"] as? Int else {
            openRadar()
            return
        }
        update(id: id, status: "read")
        let target = info["target_url"] as? String ?? "/"
        if let url = URL(string: target, relativeTo: baseURL) {
            NSWorkspace.shared.open(url)
        }
        center.removeDeliveredNotification(notification)
    }

    @objc private func openRadar() { NSWorkspace.shared.open(baseURL) }
    @objc private func quitApp() {
        timer?.invalidate()
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = RadarMenu()
app.delegate = delegate
app.run()
