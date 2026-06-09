package connect

import (
	"fmt"
	"net/http"

	"github.com/gin-gonic/gin"
)

type ConnectRequest struct {
	IP string `json:"ip"`
}

func ConnectHandler(c *gin.Context) {
	var req ConnectRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Ungültige Anfrage"})
		return
	}
	fmt.Println("Connecting to:", req.IP)
	c.JSON(http.StatusOK, gin.H{"message": "Verbindung hergestellt"})
}
