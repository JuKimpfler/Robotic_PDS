import { useState } from "react";
import ConnectContent from "../ConnectTab/ConnectTab";
import RawContent from "../RawDataTab/RawDataTab";
import GraphicContent from "../GraphicDataTab/GraphicDataTab";

function TabBar() {
    const [activeTab, setActiveTab] = useState("home")

    return(
        <div>
            <div className="flex gap-4 p-4 bg-amber-500">
                <button className="px-4 py-2 border-2 border-black rounded-2xl hover:bg-amber-100 bg-amber-50" onClick={() => setActiveTab("Connect")}>Connect</button>
                <button className="px-4 py-2 border-2 border-black rounded-2xl hover:bg-amber-100 bg-amber-50" onClick={() => setActiveTab("Raw")}>Raw Data</button>
                <button className="px-4 py-2 border-2 border-black rounded-2xl hover:bg-amber-100 bg-amber-50 " onClick={() => setActiveTab("Graphic")}>Graphical Data</button>
            </div>
            <div className="p-4 bg-amber-100">
                {activeTab === 'Connect' && <ConnectContent />}
                {activeTab === 'Raw' && <RawContent />}
                {activeTab === "Graphic" && <GraphicContent/>}
            </div>
        </div>
    )
}

export default TabBar