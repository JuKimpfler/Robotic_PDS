package main

import (
	"net/http"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"

	connect "github.com/ninja6734/FastVarLogger/modules/Connect"
)

type ConnectRequest struct {
	IP string `json:"ip"`
}

func main() {
	r := gin.Default()

	// CORS für React-Frontend erlauben
	r.Use(cors.New(cors.Config{
		AllowOrigins: []string{"http://localhost:5173"},
		AllowMethods: []string{"GET", "POST", "PUT", "DELETE"},
		AllowHeaders: []string{"Origin", "Content-Type"},
	}))

	// Routen
	r.GET("/api/hello", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"message": "Hallo vom Go-Backend!",
		})
	})

	r.POST("/api/connect", connect.ConnectHandler)

	r.Run(":8080") // läuft auf http://localhost:8080
}
