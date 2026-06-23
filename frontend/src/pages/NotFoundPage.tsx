import { useNavigate } from "react-router-dom";
import { EmptyState } from "../components/primitives/EmptyState";
import { Button } from "../components/primitives/Button";

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <EmptyState
      icon="🔍"
      title="页面不存在"
      description="你访问的页面不存在或已被移除。"
      action={<Button onClick={() => navigate("/")}>回到首页</Button>}
    />
  );
}
