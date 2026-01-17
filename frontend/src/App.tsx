import { Routes, Route } from "react-router-dom";
import OrderList from "@/pages/OrderList";
import OrderDetail from "@/pages/OrderDetail";

function App() {
  return (
    <div className="min-h-screen bg-background">
      <Routes>
        <Route path="/" element={<OrderList />} />
        <Route path="/orders/:orderId" element={<OrderDetail />} />
      </Routes>
    </div>
  );
}

export default App;
