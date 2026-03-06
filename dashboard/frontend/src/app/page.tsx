"use client";

import dynamic from "next/dynamic";

const DashboardClient = dynamic(() => import("./DashboardClient"), {
  ssr: false,
  loading: () => (
    <div className="h-screen overflow-hidden" style={{ background: "var(--bg-deep)" }} />
  ),
});

export default function DashboardPage() {
  return <DashboardClient />;
}
