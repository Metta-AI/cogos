"use client";

import { TokenManager } from "@/components/executors/TokenManager";
import { IntegrationsPanel } from "@/components/integrations/IntegrationsPanel";

interface ConfigurePanelProps {
  cogentName: string;
}

export function ConfigurePanel({ cogentName }: ConfigurePanelProps) {
  return (
    <div className="space-y-5">
      <TokenManager cogentName={cogentName} />
      <IntegrationsPanel cogentName={cogentName} />
    </div>
  );
}
