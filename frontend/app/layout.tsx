import "./globals.css";
export const metadata = {
  title: "AgentOS · Intelligence, orchestrated",
  description: "Multi-agent engineering console",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
