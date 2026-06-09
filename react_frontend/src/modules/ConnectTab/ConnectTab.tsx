import "./ConnectTab.css"
import { useState } from "react";
import axios from "axios";

function ConnectContent() {

    const [ip, setIp] = useState("")
    const [status, setStatus] = useState("")

    const handleConnect = async () => {
        try {
            const response = await axios.post('/api/connect', { ip });
            setStatus(response.data.message);
        } catch (error) {
            setStatus("Connection failed");
        }
    }
  return (
    <div>
        <h1>Connnect to Robot</h1>
        <p>To connect to the robot, please enter the IP address and port number of the robot in the fields below. Then click the "Connect" button to establish a connection.</p>
        <input type="text" placeholder="IP Address" className="input-field" value={ip} onChange={(e) => setIp(e.target.value)}/>
        <button className="border-2 border-black rounded-2xl p-2 mt-4 bg-amber-50 hover:bg-amber-100" onClick={handleConnect}>Connect</button>
        <p>{status}</p>
    </div>
  )
}

export default ConnectContent