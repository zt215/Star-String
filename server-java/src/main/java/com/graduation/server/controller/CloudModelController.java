package com.graduation.server.controller;

import com.graduation.server.common.ApiResponse;
import com.graduation.server.controller.dto.CloudDeleteRequest;
import com.graduation.server.controller.dto.CloudModelResponse;
import com.graduation.server.entity.CloudModel;
import com.graduation.server.service.CloudModelService;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;

@RestController
@RequestMapping("/api/cloud/models")
public class CloudModelController {

    private final CloudModelService service;

    public CloudModelController(CloudModelService service) {
        this.service = service;
    }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<CloudModelResponse> upload(
            @RequestParam("owner") String owner,
            @RequestParam("kind") String kind,
            @RequestParam("name") String name,
            @RequestParam("file") MultipartFile file
    ) {
        try {
            return ApiResponse.ok(service.upload(owner, kind, name, file));
        } catch (IllegalArgumentException exception) {
            return ApiResponse.error(exception.getMessage());
        } catch (IOException exception) {
            return ApiResponse.error("保存云模型文件失败");
        }
    }

    @GetMapping
    public ApiResponse<List<CloudModelResponse>> list(@RequestParam("owner") String owner) {
        return ApiResponse.ok(service.list(owner));
    }

    @GetMapping("/{id}/download")
    public ResponseEntity<Resource> download(@PathVariable Long id, @RequestParam("owner") String owner) {
        CloudModel model = service.get(owner, id);
        Resource resource = new FileSystemResource(service.pathOf(model));
        ContentDisposition disposition = ContentDisposition.attachment()
                .filename(model.getOriginalFilename(), StandardCharsets.UTF_8)
                .build();
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, disposition.toString())
                .contentLength(model.getSize())
                .body(resource);
    }

    @PostMapping("/delete")
    public ApiResponse<Void> delete(@RequestBody CloudDeleteRequest request) {
        try {
            if (request == null || request.id() == null || request.owner() == null || request.owner().isBlank()) {
                throw new IllegalArgumentException("删除参数不能为空");
            }
            service.delete(request.owner(), request.id());
            return ApiResponse.ok(null);
        } catch (IllegalArgumentException exception) {
            return ApiResponse.error(exception.getMessage());
        } catch (IOException exception) {
            return ApiResponse.error("删除云模型文件失败");
        }
    }
}
